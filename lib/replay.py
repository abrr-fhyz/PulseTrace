"""Per-iteration replay state derived from a finished run.

Per-iter snapshots are not persisted during a run; only the FINAL posts.json /
clusters.json exist. We reconstruct "state at iteration N" by attributing each
post to the iteration in which its originating query first ran, then filtering.
Clusters stay as the final set — re-clustering a sub-frame needs embeddings and
is out of scope; the slider rewinds POSTS and QUERY coverage.
"""
from __future__ import annotations

import ast
from typing import Any, Callable

from .store import read_json


def max_iter(run: dict | None) -> int:
    queries = (run or {}).get("queries") or []
    iters = [int(q.get("iter", 1)) for q in queries if isinstance(q, dict)]
    return max(iters) if iters else 1


def _query_iter_map(run: dict | None) -> dict[str, int]:
    """Map each query string to the EARLIEST iteration it appeared in."""
    out: dict[str, int] = {}
    for q in (run or {}).get("queries") or []:
        if not isinstance(q, dict):
            continue
        qs = q.get("q")
        if not isinstance(qs, str):
            continue
        it = int(q.get("iter", 1))
        if qs not in out or it < out[qs]:
            out[qs] = it
    return out


def _raw_of(post: dict) -> dict:
    raw = post.get("raw")
    if isinstance(raw, dict):
        return raw
    # raw may arrive stringified, e.g. "{'query': '...', 'shot': '...'}".
    # ast.literal_eval parses Python literals only; it cannot execute code.
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, SyntaxError):
            return {}
    return {}


def post_iter(post: dict, query_iters: dict[str, int]) -> int:
    """Iteration a post originated in.

    Heuristic: cross-reference the post's query string (raw["query"]) against
    the run's query log. The shot id ("q0_s0_...") only encodes the query's
    position WITHIN an iteration, not a global iteration, so it can't be used
    directly. If the query is missing/unknown (non-FB sources don't record one,
    or the query was rewritten), we conservatively treat the post as iter 1 so
    it appears from the very first frame rather than vanishing.
    """
    q = _raw_of(post).get("query")
    if isinstance(q, str) and q in query_iters:
        return query_iters[q]
    return 1


def posts_through_iter(
    posts: list[dict], iter_n: int, *, run: dict | None = None
) -> list[dict]:
    if not posts:
        return []
    query_iters = _query_iter_map(run)
    return [p for p in posts if post_iter(p, query_iters) <= iter_n]


def queries_through_iter(run: dict | None, iter_n: int) -> list[dict]:
    out = []
    for q in (run or {}).get("queries") or []:
        if isinstance(q, dict) and int(q.get("iter", 1)) <= iter_n:
            out.append(q)
    return out


def frame(
    run_id: str, iter_n: int, *, read: Callable[[str, str], Any] = read_json
) -> dict:
    run = read(run_id, "run.json")
    posts = read(run_id, "posts.json") or []
    through = posts_through_iter(posts, iter_n, run=run)
    return {
        "iter": iter_n,
        "max_iter": max_iter(run),
        "n_posts": len(through),
        "posts": through,
        "queries": queries_through_iter(run, iter_n),
    }
