"""Influence score: engagement + recency decay."""
from __future__ import annotations
import math
import time
from .connectors.base import Post


HALF_LIFE_DAYS = 7.0


def recency(ts: int, now: int | None = None) -> float:
    if ts <= 0:
        return 0.0
    now = now or int(time.time())
    days = max(0.0, (now - ts) / 86400.0)
    return 0.5 ** (days / HALF_LIFE_DAYS)


def influence(p: Post, now: int | None = None) -> float:
    return (
        math.log1p(p.reactions)
        + 2.0 * math.log1p(p.comments)
        + 3.0 * math.log1p(p.shares)
        + 0.5 * recency(p.ts, now)
    )


def top_n(posts: list[Post], n: int = 5) -> list[Post]:
    return sorted(posts, key=influence, reverse=True)[:n]
