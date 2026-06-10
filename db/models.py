"""Typed records shared by the storage clients.

These mirror the JSON shapes already produced by the file-based pipeline
(`lib/store.py` writes `posts.json` / `run.json`) so the DB layer is a
drop-in *augmentation*, not a rewrite. Validation happens at the DB boundary
only — the in-process pipeline keeps using plain dicts.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from pydantic import BaseModel, Field, field_validator


def _engagement(reactions: int, comments: int, shares: int) -> float:
    """Deterministic fallback when influence.py hasn't scored the post yet."""
    return float(reactions) + 2.0 * float(comments) + 3.0 * float(shares)


class RunRecord(BaseModel):
    run_id: str
    topic: str
    topic_id: str
    sources: list[str] = Field(default_factory=list)
    status: str = "running"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    n_posts: int = 0
    meta: dict = Field(default_factory=dict)
    owner_email: str | None = None


class PostRecord(BaseModel):
    id: str
    run_id: str
    topic_id: str
    source: str
    text: str = ""
    author: str = ""
    url: str = ""
    ts: datetime
    crawl_date: date
    reactions: int = 0
    comments: int = 0
    shares: int = 0
    engagement_score: float = 0.0
    embedding: list[float] | None = None
    raw: dict = Field(default_factory=dict)

    @field_validator("ts", mode="before")
    @classmethod
    def _coerce_ts(cls, v: object) -> datetime:
        if isinstance(v, datetime):
            return v
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(float(v), tz=timezone.utc)
        if isinstance(v, str) and v:
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                pass
        return datetime.now(tz=timezone.utc)

    @classmethod
    def from_raw(cls, post: dict, *, run_id: str, topic_id: str) -> "PostRecord":
        """Build from a pipeline post dict (id, source, text, ts, reactions…)."""
        reactions = int(post.get("reactions", 0) or 0)
        comments = int(post.get("comments", 0) or 0)
        shares = int(post.get("shares", 0) or 0)
        score = post.get("engagement_score")
        if score is None:
            score = _engagement(reactions, comments, shares)
        ts = cls._coerce_ts(post.get("ts"))
        return cls(
            id=str(post.get("id") or f"{run_id}:{abs(hash(post.get('text', ''))) % 10**12}"),
            run_id=run_id,
            topic_id=topic_id,
            source=str(post.get("source", "")),
            text=str(post.get("text", "")),
            author=str(post.get("author", "")),
            url=str(post.get("url", "")),
            ts=ts,
            crawl_date=ts.date(),
            reactions=reactions,
            comments=comments,
            shares=shares,
            engagement_score=float(score),
            embedding=post.get("embedding"),
            raw=post.get("raw", {}) if isinstance(post.get("raw"), dict) else {},
        )
