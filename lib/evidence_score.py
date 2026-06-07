"""Pure evidence-ranking math. No IO, no LLM."""
from __future__ import annotations
import math
from .connectors.base import Post
from .influence import recency as _recency

SOURCE_CREDIBILITY: dict[str, float] = {
    "hn": 0.8, "reddit": 0.6, "facebook": 0.5, "x": 0.5, "instagram": 0.4,
}
SOURCE_CATEGORY: dict[str, str] = {
    "hn": "forums", "reddit": "forums", "facebook": "social",
    "x": "social", "instagram": "social",
}
_RANK_WEIGHTS = ("credibility", "data_quality", "sample_size", "recency", "corroboration")
_COMPUTED_WEIGHT = 0.6
_LLM_WEIGHT = 0.4


def engagement(posts: list[Post]) -> int:
    return sum(p.reactions + p.comments + p.shares for p in posts)


def source_diversity(posts: list[Post]) -> int:
    return len({p.source for p in posts})


def corroboration(posts: list[Post]) -> float:
    n = source_diversity(posts)
    if n <= 0:
        return 0.0
    return min(1.0, (n - 1) / 3.0)


def credibility(posts: list[Post]) -> float:
    if not posts:
        return 0.0
    vals = [SOURCE_CREDIBILITY.get(p.source, 0.5) for p in posts]
    return sum(vals) / len(vals)


def sample_size_norm(n_members: int, max_members: int) -> float:
    if max_members <= 0 or n_members <= 0:
        return 0.0
    return min(1.0, n_members / max_members)


def recency_score(posts: list[Post], now: int) -> float:
    tss = [p.ts for p in posts if p.ts]
    if not tss:
        return 0.0
    return max(_recency(ts, now) for ts in tss)


def data_quality(posts: list[Post]) -> float:
    if not posts:
        return 0.0
    avg_len = sum(len(p.text or "") for p in posts) / len(posts)
    len_score = min(1.0, avg_len / 300.0)
    eng_score = min(1.0, math.log1p(engagement(posts)) / math.log1p(50))
    return 0.5 * len_score + 0.5 * eng_score


def rank(posts: list[Post], max_members: int, now: int) -> dict[str, float]:
    if not posts:
        return {k: 0.0 for k in _RANK_WEIGHTS}
    return {
        "credibility": credibility(posts),
        "data_quality": data_quality(posts),
        "sample_size": sample_size_norm(len(posts), max_members),
        "recency": recency_score(posts, now),
        "corroboration": corroboration(posts),
    }


def strength_bucket(ranking: dict[str, float]) -> str:
    if not ranking:
        return "weak"
    mean = sum(ranking.values()) / len(ranking)
    if mean >= 0.66:
        return "strong"
    if mean >= 0.33:
        return "moderate"
    return "weak"


def blend(computed_norm: float, llm_conf: float) -> float:
    v = _COMPUTED_WEIGHT * computed_norm + _LLM_WEIGHT * llm_conf
    return max(0.0, min(1.0, v))


def category_for(source: str) -> str:
    return SOURCE_CATEGORY.get(source, "social")
