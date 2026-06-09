"""MongoDB hot/cold document tiering.

Two collections back a simple lifecycle:

    posts_hot   active crawl-session data + recent posts (queried live)
    posts_cold  compacted archive of aged-out sessions (cheap, rarely read)

`archive_aged()` moves documents past a freshness window from hot → cold,
compacting them on the way. A TTL index on the hot collection is a *backstop*
only (set well beyond the archive window) so nothing lingers if the archival
job never runs.

Pool sizing follows the long-running Flask server (OLTP, low concurrency) the
rest of PulseTrace assumes — see inline rationale. One client is created and
reused; never close it per request.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .models import PostRecord

log = logging.getLogger("pulsetrace.db.mongo")

try:  # heavy optional dep
    from pymongo import ASCENDING, DESCENDING, MongoClient as _PyMongoClient, UpdateOne
    from pymongo.errors import PyMongoError
    _HAVE_PYMONGO = True
except ImportError:  # pragma: no cover
    _HAVE_PYMONGO = False

# Backstop eviction for hot docs (days). Must exceed the archive window so
# archival always wins the race; TTL only catches orphans.
HOT_TTL_DAYS = int(os.environ.get("PULSE_HOT_TTL_DAYS", "45"))


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _compact(doc: dict) -> dict:
    """Shrink a hot post for cold storage: drop the heavy raw blob, keep the
    signal needed for archival analytics. This is the tiering policy — adjust
    here if cold queries need more fields retained."""
    keep = {k: v for k, v in doc.items() if k != "raw"}
    keep["compacted"] = True
    return keep


class MongoClient:
    def __init__(
        self,
        uri: str | None = None,
        *,
        db_name: str | None = None,
    ) -> None:
        self._uri = uri or os.environ.get("MONGODB_URI", "")
        self._db_name = db_name or os.environ.get("MONGODB_DB", "pulsetrace")
        self._client: "_PyMongoClient | None" = None
        self.enabled = bool(self._uri) and _HAVE_PYMONGO
        if self._uri and not _HAVE_PYMONGO:
            log.warning("MONGODB_URI set but pymongo not installed; Mongo disabled.")
        if self.enabled:
            try:
                self._client = _PyMongoClient(
                    self._uri,
                    # Long-running server, modest concurrency: 20 covers the
                    # Flask worker + background agent threads with headroom.
                    maxPoolSize=int(os.environ.get("MONGODB_MAX_POOL", "20")),
                    minPoolSize=int(os.environ.get("MONGODB_MIN_POOL", "2")),  # pre-warmed for SSE bursts
                    maxIdleTimeMS=300_000,    # 5 min — stable server, keep warm
                    connectTimeoutMS=5_000,   # fail fast on a bad host
                    socketTimeoutMS=30_000,   # short OLTP writes/reads
                    serverSelectionTimeoutMS=5_000,
                    retryWrites=True,
                )
                self._client.admin.command("ping")
                self.ensure_indexes()
            except PyMongoError as exc:
                log.error("Mongo connect failed: %s; falling back to file storage.", exc)
                self.enabled = False
                self._client = None

    # --------------------------------------------------------------- handles
    @property
    def _db(self) -> Any:
        return self._client[self._db_name]

    @property
    def hot(self) -> Any:
        return self._db["posts_hot"]

    @property
    def cold(self) -> Any:
        return self._db["posts_cold"]

    @property
    def sessions(self) -> Any:
        return self._db["sessions"]

    def ensure_indexes(self) -> None:
        if not self.enabled:
            return
        try:
            self.hot.create_index([("id", ASCENDING)], unique=True, name="uq_id")
            self.hot.create_index([("session_id", ASCENDING)], name="ix_session")
            self.hot.create_index(
                [("topic_id", ASCENDING), ("engagement_score", DESCENDING)],
                name="ix_topic_engagement",
            )
            self.hot.create_index([("created_at", ASCENDING)],
                                  expireAfterSeconds=HOT_TTL_DAYS * 86_400,
                                  name="ttl_created")
            self.cold.create_index([("session_id", ASCENDING)], name="ix_cold_session")
            self.cold.create_index([("topic_id", ASCENDING)], name="ix_cold_topic")
            self.sessions.create_index([("session_id", ASCENDING)], unique=True,
                                       name="uq_session")
        except PyMongoError as exc:
            log.error("ensure_indexes failed: %s", exc)

    # --------------------------------------------------------------- writes
    def write_session(
        self,
        session_id: str,
        topic_id: str,
        posts: Iterable[PostRecord],
        *,
        meta: dict | None = None,
    ) -> int:
        """Upsert the session doc + its posts into the hot tier. Idempotent."""
        if not self.enabled:
            return 0
        rows = list(posts)
        try:
            self.sessions.update_one(
                {"session_id": session_id},
                {"$set": {"session_id": session_id, "topic_id": topic_id,
                          "meta": meta or {}, "n_posts": len(rows),
                          "updated_at": _now()},
                 "$setOnInsert": {"created_at": _now()}},
                upsert=True,
            )
            if not rows:
                return 0
            now = _now()
            ops = []
            for r in rows:
                doc = r.model_dump(mode="json")
                doc["session_id"] = session_id
                doc["created_at"] = now
                ops.append(UpdateOne({"id": r.id}, {"$set": doc}, upsert=True))
            res = self.hot.bulk_write(ops, ordered=False)
            return (res.upserted_count or 0) + (res.modified_count or 0)
        except PyMongoError as exc:
            log.error("write_session(%s) failed: %s", session_id, exc)
            return 0

    # --------------------------------------------------------------- reads
    def get_session(self, session_id: str, *, limit: int = 1000) -> list[dict]:
        """Hot tier first; fall through to cold for archived sessions."""
        if not self.enabled:
            return []
        try:
            cur = self.hot.find({"session_id": session_id}, {"_id": 0}).limit(limit)
            docs = list(cur)
            if docs:
                return docs
            return list(self.cold.find({"session_id": session_id}, {"_id": 0}).limit(limit))
        except PyMongoError as exc:
            log.error("get_session(%s) failed: %s", session_id, exc)
            return []

    def top_posts(self, topic_id: str, *, limit: int = 20) -> list[dict]:
        """Engagement leaderboard from the hot tier (uses ix_topic_engagement)."""
        if not self.enabled:
            return []
        try:
            cur = (self.hot.find({"topic_id": topic_id}, {"_id": 0})
                   .sort("engagement_score", DESCENDING).limit(limit))
            return list(cur)
        except PyMongoError as exc:
            log.error("top_posts(%s) failed: %s", topic_id, exc)
            return []

    # --------------------------------------------------------------- lifecycle
    def archive_aged(self, *, max_age_days: int | None = None, batch: int = 500) -> dict:
        """Move hot docs older than `max_age_days` into the compacted cold tier
        and delete them from hot. Runs before the TTL backstop kicks in.
        Defaults to env PULSE_ARCHIVE_AGE_DAYS (14). Returns {'archived', 'sessions'}."""
        if not self.enabled:
            return {"archived": 0, "sessions": 0}
        if max_age_days is None:
            max_age_days = int(os.environ.get("PULSE_ARCHIVE_AGE_DAYS", "14"))
        cutoff = _now() - timedelta(days=max_age_days)
        archived = 0
        sessions: set[str] = set()
        try:
            while True:
                aged = list(self.hot.find({"created_at": {"$lt": cutoff}},
                                          {"_id": 0}).limit(batch))
                if not aged:
                    break
                cold_docs = [_compact(d) for d in aged]
                ids = [d["id"] for d in aged]
                self.cold.bulk_write(
                    [UpdateOne({"id": d["id"]}, {"$set": d}, upsert=True) for d in cold_docs],
                    ordered=False,
                )
                self.hot.delete_many({"id": {"$in": ids}})
                archived += len(ids)
                sessions.update(d.get("session_id", "") for d in aged)
                if len(aged) < batch:
                    break
            sessions.discard("")
            return {"archived": archived, "sessions": len(sessions)}
        except PyMongoError as exc:
            log.error("archive_aged failed after %d docs: %s", archived, exc)
            return {"archived": archived, "sessions": len(sessions)}

    def health(self) -> dict:
        if not self.enabled:
            return {"enabled": False, "backend": "file"}
        try:
            return {
                "enabled": True,
                "backend": "mongo",
                "hot": self.hot.estimated_document_count(),
                "cold": self.cold.estimated_document_count(),
            }
        except PyMongoError as exc:
            return {"enabled": True, "backend": "mongo", "error": str(exc)}

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self.enabled = False
