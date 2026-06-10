"""Postgres + pgvector client (Supabase-compatible).

Replaces the local FAISS `IndexFlatIP` with topic/session-scoped pgvector
search and adds relational leaderboard queries over a partitioned `posts`
table. Activates only when a connection string is present; otherwise
`enabled is False` and callers fall back to file-based storage.

Connection string resolution (first hit wins):
    DATABASE_URL  >  SUPABASE_DB_URL

The `supabase-py` REST client is wired in lazily for convenience RPC/storage,
but all hot-path writes/reads go through a psycopg2 `ThreadedConnectionPool`
for raw SQL + pgvector.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import date
from typing import Iterable, Iterator

from .models import PostRecord, RunRecord

log = logging.getLogger("pulsetrace.db.supabase")

try:  # heavy optional dep
    import psycopg2
    from psycopg2.extras import RealDictCursor, execute_values
    from psycopg2.pool import ThreadedConnectionPool
    _HAVE_PG = True
except ImportError:  # pragma: no cover - exercised only when dep missing
    _HAVE_PG = False

EMBED_DIM = int(os.environ.get("PULSE_EMBED_DIM", "3072"))


def _vec_literal(embedding: list[float] | None) -> str | None:
    """pgvector/halfvec text format: '[1,2,3]'. None → SQL NULL."""
    if not embedding:
        return None
    return "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"


def _topic_slug(topic_id: str) -> str:
    """Safe suffix for a partition table name (identifiers can't be quoted here)."""
    safe = "".join(c if c.isalnum() else "_" for c in topic_id.lower())
    return (safe[:40] or "topic").strip("_") or "topic"


class SupabaseClient:
    def __init__(self, dsn: str | None = None, *, minconn: int | None = None, maxconn: int | None = None) -> None:
        self._dsn = dsn or os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL", "")
        minconn = minconn if minconn is not None else int(os.environ.get("PG_POOL_MIN", "1"))
        maxconn = maxconn if maxconn is not None else int(os.environ.get("PG_POOL_MAX", "8"))
        self._pool: "ThreadedConnectionPool | None" = None
        self.enabled = bool(self._dsn) and _HAVE_PG
        if self._dsn and not _HAVE_PG:
            log.warning("DATABASE_URL set but psycopg2 not installed; Postgres disabled.")
        if self.enabled:
            try:
                self._pool = ThreadedConnectionPool(minconn, maxconn, self._dsn)
            except psycopg2.Error as exc:
                log.error("Postgres pool init failed: %s; falling back to file storage.", exc)
                self.enabled = False

    # ------------------------------------------------------------------ infra
    @contextmanager
    def _conn(self) -> Iterator["psycopg2.extensions.connection"]:
        if not self.enabled or self._pool is None:
            raise RuntimeError("SupabaseClient is not enabled")
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except psycopg2.Error:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def apply_schema(self, sql_path: str = "db/schema.sql") -> bool:
        if not self.enabled:
            return False
        try:
            with open(sql_path, "r", encoding="utf-8") as fh:
                ddl = fh.read()
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute(ddl)
            return True
        except (OSError, psycopg2.Error) as exc:
            log.error("apply_schema failed: %s", exc)
            return False

    def close(self) -> None:
        if self._pool is not None:
            self._pool.closeall()
            self._pool = None
            self.enabled = False

    # ------------------------------------------------------------- partitions
    def _ensure_partition(self, cur: "psycopg2.extensions.cursor", d: date, topic_id: str) -> None:
        """Idempotently create the monthly range partition (sub-partitioned by
        topic) and the topic leaf for (month, topic_id). DEFAULT leaves in
        schema.sql guarantee an insert never rejects even if this is skipped."""
        month = f"y{d.year:04d}m{d.month:02d}"
        m_start = date(d.year, d.month, 1)
        m_end = date(d.year + (d.month == 12), (d.month % 12) + 1, 1)
        range_part = f"posts_{month}"
        leaf = f"{range_part}_{_topic_slug(topic_id)}"
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {range_part} PARTITION OF posts "
            f"FOR VALUES FROM (%s) TO (%s) PARTITION BY LIST (topic_id)",
            (m_start.isoformat(), m_end.isoformat()),
        )
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {range_part}_default "
            f"PARTITION OF {range_part} DEFAULT"
        )
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {leaf} PARTITION OF {range_part} "
            f"FOR VALUES IN (%s)",
            (topic_id,),
        )
        # Partitions don't inherit the parent's RLS flag; enable per leaf so
        # they aren't exposed via PostgREST (Supabase advisor 0013).
        for tbl in (range_part, f"{range_part}_default", leaf):
            cur.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")

    # ----------------------------------------------------------------- writes
    def upsert_run(self, run: RunRecord) -> bool:
        if not self.enabled:
            return False
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO runs (run_id, topic, topic_id, sources, status,
                                      started_at, finished_at, n_posts, meta, owner_email)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (run_id) DO UPDATE SET
                        status      = EXCLUDED.status,
                        finished_at = EXCLUDED.finished_at,
                        n_posts     = EXCLUDED.n_posts,
                        meta        = EXCLUDED.meta,
                        owner_email = COALESCE(runs.owner_email, EXCLUDED.owner_email)
                    """,
                    (run.run_id, run.topic, run.topic_id, run.sources, run.status,
                     run.started_at, run.finished_at, run.n_posts,
                     psycopg2.extras.Json(run.meta) if _HAVE_PG else run.meta,
                     run.owner_email),
                )
            return True
        except psycopg2.Error as exc:
            log.error("upsert_run(%s) failed: %s", run.run_id, exc)
            return False

    def insert_posts(self, posts: Iterable[PostRecord], *, batch: int = 200) -> int:
        """Batched upsert into the partitioned table. Returns rows written."""
        if not self.enabled:
            return 0
        rows = list(posts)
        if not rows:
            return 0
        written = 0
        # Pre-create every (month, topic) partition touched by this batch.
        wanted = {(r.crawl_date, r.topic_id) for r in rows}
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    for d, tid in wanted:
                        self._ensure_partition(cur, d, tid)
                template = (
                    "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::halfvec,%s)"
                )
                sql = """
                    INSERT INTO posts (id, run_id, topic_id, source, text, author,
                        url, ts, crawl_date, reactions, comments, shares,
                        embedding, engagement_score)
                    VALUES %s
                    ON CONFLICT (id, topic_id, crawl_date) DO UPDATE SET
                        engagement_score = EXCLUDED.engagement_score,
                        embedding = COALESCE(EXCLUDED.embedding, posts.embedding)
                """
                for i in range(0, len(rows), batch):
                    chunk = rows[i:i + batch]
                    values = [
                        (r.id, r.run_id, r.topic_id, r.source, r.text, r.author,
                         r.url, r.ts, r.crawl_date, r.reactions, r.comments,
                         r.shares, _vec_literal(r.embedding), r.engagement_score)
                        for r in chunk
                    ]
                    with self._conn() as conn, conn.cursor() as cur:
                        for d, tid in {(r.crawl_date, r.topic_id) for r in chunk}:
                            self._ensure_partition(cur, d, tid)
                        execute_values(cur, sql, values, template=template, page_size=batch)
                        written += cur.rowcount if cur.rowcount > 0 else len(chunk)
            return written
        except psycopg2.Error as exc:
            log.error("insert_posts failed after %d rows: %s", written, exc)
            return written

    # ------------------------------------------------------------------ reads
    def top_posts_by_engagement(
        self, topic_id: str, *, since: date | None = None, limit: int = 20
    ) -> list[dict]:
        """Leaderboard query — served by the B-Tree on engagement_score with
        partition pruning on topic_id (and crawl_date when `since` is given)."""
        if not self.enabled:
            return []
        try:
            with self._conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, source, author, url, text, engagement_score,
                           reactions, comments, shares, crawl_date
                    FROM posts
                    WHERE topic_id = %s AND (%s::date IS NULL OR crawl_date >= %s)
                    ORDER BY engagement_score DESC
                    LIMIT %s
                    """,
                    (topic_id, since, since, limit),
                )
                return [dict(r) for r in cur.fetchall()]
        except psycopg2.Error as exc:
            log.error("top_posts_by_engagement(%s) failed: %s", topic_id, exc)
            return []

    def vector_search(
        self, query_embedding: list[float], *, topic_id: str | None = None, k: int = 8
    ) -> list[dict]:
        """pgvector cosine search (replaces FAISS). Topic-scoped when given —
        closes the 'no SQL scoping' gap. Returns rows with a `score` in [0,1]."""
        if not self.enabled or not query_embedding:
            return []
        qv = _vec_literal(query_embedding)
        try:
            with self._conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, source, author, url, text, topic_id,
                           1 - (embedding <=> %s::halfvec) AS score
                    FROM posts
                    WHERE embedding IS NOT NULL
                      AND (%s::text IS NULL OR topic_id = %s)
                    ORDER BY embedding <=> %s::halfvec
                    LIMIT %s
                    """,
                    (qv, topic_id, topic_id, qv, k),
                )
                return [dict(r) for r in cur.fetchall()]
        except psycopg2.Error as exc:
            log.error("vector_search failed: %s", exc)
            return []

    # ------------------------------------------------------------- clusters
    def insert_clusters(self, run_id: str, topic_id: str, clusters: Iterable[dict]) -> int:
        """Upsert clusters.json rows (label, sentiment split, members, centroid)."""
        if not self.enabled:
            return 0
        rows = list(clusters)
        if not rows:
            return 0
        try:
            values = []
            for c in rows:
                s = c.get("sentiment") or {}
                values.append((
                    run_id, int(c.get("id", 0)), topic_id,
                    str(c.get("label", "")), str(c.get("desc", "")),
                    float(s.get("pos", 0) or 0), float(s.get("neu", 0) or 0),
                    float(s.get("neg", 0) or 0),
                    list(c.get("members", []) or []), list(c.get("top_posts", []) or []),
                    _vec_literal(c.get("centroid")),
                ))
            with self._conn() as conn, conn.cursor() as cur:
                execute_values(
                    cur,
                    """
                    INSERT INTO clusters (run_id, cluster_id, topic_id, label, descr,
                        sentiment_pos, sentiment_neu, sentiment_neg, members, top_posts, centroid)
                    VALUES %s
                    ON CONFLICT (run_id, cluster_id) DO UPDATE SET
                        label=EXCLUDED.label, descr=EXCLUDED.descr,
                        sentiment_pos=EXCLUDED.sentiment_pos, sentiment_neu=EXCLUDED.sentiment_neu,
                        sentiment_neg=EXCLUDED.sentiment_neg, members=EXCLUDED.members,
                        top_posts=EXCLUDED.top_posts,
                        centroid=COALESCE(EXCLUDED.centroid, clusters.centroid)
                    """,
                    values,
                    template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::halfvec)",
                )
            return len(rows)
        except psycopg2.Error as exc:
            log.error("insert_clusters failed: %s", exc)
            return 0

    def get_clusters(self, run_id: str) -> list[dict]:
        if not self.enabled:
            return []
        try:
            with self._conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT run_id, cluster_id, topic_id, label, descr, sentiment_pos, "
                    "sentiment_neu, sentiment_neg, members, top_posts FROM clusters "
                    "WHERE run_id=%s ORDER BY cluster_id",
                    (run_id,),
                )
                return [dict(r) for r in cur.fetchall()]
        except psycopg2.Error as exc:
            log.error("get_clusters(%s) failed: %s", run_id, exc)
            return []

    def list_runs(self, *, owner_email: str | None = None, limit: int = 50) -> list[dict] | None:
        """Returns rows on success (possibly empty), or None if the DB is
        unreachable so the caller can fall back to disk *only* on failure.

        `owner_email=None` lists every run (single-user/local mode); a string
        scopes to that owner, hiding other users' and legacy NULL-owner runs."""
        if not self.enabled:
            return None
        try:
            where = "WHERE owner_email = %s" if owner_email else ""
            params: tuple = (owner_email, limit) if owner_email else (limit,)
            with self._conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT run_id, topic, started_at, finished_at, n_posts, status "
                    f"FROM runs {where} ORDER BY started_at DESC NULLS LAST LIMIT %s",
                    params,
                )
                return [dict(r) for r in cur.fetchall()]
        except psycopg2.Error as exc:
            log.error("list_runs failed: %s", exc)
            return None

    def delete_run(self, run_id: str, *, owner_email: str | None = None) -> bool:
        if not self.enabled:
            return False
        try:
            with self._conn() as conn, conn.cursor() as cur:
                if owner_email:
                    cur.execute("SELECT owner_email FROM runs WHERE run_id=%s", (run_id,))
                    row = cur.fetchone()
                    if row and row[0] not in (None, owner_email):
                        return False
                for table in ("run_artifacts", "clusters", "posts", "runs"):
                    cur.execute(f"DELETE FROM {table} WHERE run_id=%s", (run_id,))
            return True
        except psycopg2.Error as exc:
            log.error("delete_run(%s) failed: %s", run_id, exc)
            return False

    # ------------------------------------------------------------ artifacts
    def upsert_artifact(self, run_id: str, name: str, data: object, *, topic_id: str = "") -> bool:
        """Persist any per-run artifact (evidence/ranked/orchestration_summary) as jsonb."""
        if not self.enabled:
            return False
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO run_artifacts (run_id, name, topic_id, data)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (run_id, name) DO UPDATE SET
                        data=EXCLUDED.data, topic_id=EXCLUDED.topic_id
                    """,
                    (run_id, name, topic_id, psycopg2.extras.Json(data)),
                )
            return True
        except psycopg2.Error as exc:
            log.error("upsert_artifact(%s/%s) failed: %s", run_id, name, exc)
            return False

    def get_artifact(self, run_id: str, name: str) -> object | None:
        if not self.enabled:
            return None
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT data FROM run_artifacts WHERE run_id=%s AND name=%s",
                    (run_id, name),
                )
                row = cur.fetchone()
                return row[0] if row else None
        except psycopg2.Error as exc:
            log.error("get_artifact(%s/%s) failed: %s", run_id, name, exc)
            return None

    # ----------------------------------------------------------- conversations
    def upsert_conversation(self, conv: dict) -> bool:
        if not self.enabled:
            return False
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversations
                        (id, topic_id, run_id, title, summary, archived_count, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s, now())
                    ON CONFLICT (id) DO UPDATE SET
                        title=EXCLUDED.title, summary=EXCLUDED.summary,
                        archived_count=EXCLUDED.archived_count, updated_at=now()
                    """,
                    (conv["id"], conv["topic_id"], conv["run_id"],
                     conv.get("title", "New chat"), conv.get("summary", ""),
                     int(conv.get("archived_count", 0))),
                )
            return True
        except (psycopg2.Error, KeyError) as exc:
            # KeyError: a malformed conv dict degrades to False, never crashes the chat write.
            log.error("upsert_conversation(%s) failed: %s", conv.get("id"), exc)
            return False

    def insert_message(self, conversation_id: str, role: str, content: str,
                       metadata: dict | None = None) -> bool:
        if not self.enabled:
            return False
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO messages (conversation_id, role, content, metadata) "
                    "VALUES (%s,%s,%s,%s)",
                    (conversation_id, role, content,
                     psycopg2.extras.Json(metadata or {})),
                )
            return True
        except psycopg2.Error as exc:
            log.error("insert_message(%s) failed: %s", conversation_id, exc)
            return False

    def get_conversation(self, conv_id: str) -> dict | None:
        if not self.enabled:
            return None
        try:
            with self._conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, topic_id, run_id, title, summary, archived_count "
                    "FROM conversations WHERE id=%s",
                    (conv_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
        except psycopg2.Error as exc:
            log.error("get_conversation(%s) failed: %s", conv_id, exc)
            return None

    def get_messages(self, conv_id: str) -> list[dict]:
        if not self.enabled:
            return []
        try:
            with self._conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT role, content, metadata, "
                    "extract(epoch from created_at)::bigint AS ts "
                    "FROM messages WHERE conversation_id=%s ORDER BY created_at, id",
                    (conv_id,),
                )
                return [dict(r) for r in cur.fetchall()]
        except psycopg2.Error as exc:
            log.error("get_messages(%s) failed: %s", conv_id, exc)
            return []

    def list_conversations(self, topic_id: str) -> list[dict]:
        if not self.enabled:
            return []
        try:
            with self._conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT c.id, c.title,
                           extract(epoch from c.created_at)::bigint AS created,
                           extract(epoch from c.updated_at)::bigint AS updated,
                           (SELECT count(*) FROM messages m
                              WHERE m.conversation_id = c.id) AS message_count
                    FROM conversations c
                    WHERE c.topic_id = %s
                    ORDER BY c.updated_at DESC
                    """,
                    (topic_id,),
                )
                return [dict(r) for r in cur.fetchall()]
        except psycopg2.Error as exc:
            log.error("list_conversations(%s) failed: %s", topic_id, exc)
            return []

    def delete_conversation(self, conv_id: str) -> bool:
        if not self.enabled:
            return False
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM conversations WHERE id=%s", (conv_id,))
                return cur.rowcount > 0
        except psycopg2.Error as exc:
            log.error("delete_conversation(%s) failed: %s", conv_id, exc)
            return False

    def health(self) -> dict:
        if not self.enabled:
            return {"enabled": False, "backend": "file"}
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM posts")
                n = cur.fetchone()[0]
                cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                has_vec = cur.fetchone() is not None
            return {"enabled": True, "backend": "postgres", "posts": n, "pgvector": has_vec}
        except psycopg2.Error as exc:
            return {"enabled": True, "backend": "postgres", "error": str(exc)}
