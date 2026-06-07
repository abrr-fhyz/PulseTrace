"""Coordination / astroturf radar.

Near-identical posts authored by *different* accounts in a tight window are the
signature of a coordinated campaign. `lib.dedup` finds these near-dupes to drop
them; here we keep them and surface the ones that look orchestrated.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .dedup import simhash, hamming


def group_near_dupes(texts: list[str], threshold: int = 14) -> list[list[int]]:
    """Group text indices into near-duplicate buckets (greedy by representative)."""
    groups: list[list[int]] = []
    reps: list[int] = []
    for i, t in enumerate(texts):
        h = simhash(t)
        for gi, rep in enumerate(reps):
            if hamming(h, rep) <= threshold:
                groups[gi].append(i)
                break
        else:
            groups.append([i])
            reps.append(h)
    return groups


@dataclass
class Campaign:
    post_indices: list[int]
    authors: list[str]
    n_copies: int
    n_authors: int
    span_seconds: int
    score: float
    sample_text: str = ""
    examples: list[dict] = field(default_factory=list)


def _tightness(span_seconds: int) -> float:
    return 1.0 / (1.0 + max(span_seconds, 0) / 3600.0)


def detect_campaigns(posts: list[dict], min_authors: int = 3,
                     threshold: int = 14) -> list[Campaign]:
    """Flag near-dupe groups posted by >= `min_authors` distinct accounts.

    Score = distinct_authors x copies x time-tightness; tighter bursts rank
    higher. Returned sorted by score descending. Leads, not verdicts.
    """
    if not posts:
        return []
    groups = group_near_dupes([str(p.get("text", "")) for p in posts], threshold)
    camps: list[Campaign] = []
    for g in groups:
        authors = sorted({
            str(posts[i].get("author")).strip()
            for i in g
            if str(posts[i].get("author") or "").strip()
        })
        if len(authors) < min_authors:
            continue
        ts = [int(posts[i].get("ts", 0) or 0) for i in g]
        span = max(ts) - min(ts) if ts else 0
        n_copies = len(g)
        score = len(authors) * n_copies * _tightness(span)
        camps.append(Campaign(
            post_indices=list(g),
            authors=authors,
            n_copies=n_copies,
            n_authors=len(authors),
            span_seconds=span,
            score=score,
            sample_text=str(posts[g[0]].get("text", ""))[:280],
            examples=[{
                "author": posts[i].get("author"),
                "ts": posts[i].get("ts"),
                "text": str(posts[i].get("text", ""))[:280],
                "url": posts[i].get("url"),
            } for i in g[:6]],
        ))
    camps.sort(key=lambda c: c.score, reverse=True)
    return camps
