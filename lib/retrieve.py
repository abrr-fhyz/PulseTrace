"""Hybrid retrieval: dense (FAISS) + BM25, merged via Reciprocal Rank Fusion."""
from __future__ import annotations

import json
import re

import numpy as np

from .embed import embed_texts
from .store import run_dir

RRF_K = 60

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def rrf_merge(rankings: list[list[str]], k: int = RRF_K) -> list[str]:
    """Reciprocal Rank Fusion. score(id) = sum 1/(k + rank0) across rankings."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda i: scores[i], reverse=True)


def _load_posts(run_id: str) -> list[dict]:
    path = run_dir(run_id) / "posts.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


def dense_search(run_id: str, query: str, n: int) -> list[str]:
    import faiss

    d = run_dir(run_id)
    idx_path = d / "index.faiss"
    if not idx_path.exists():
        return []
    idx = faiss.read_index(str(idx_path))
    ids = json.loads((d / "ids.json").read_text())
    qvec = embed_texts([query]).astype(np.float32)
    _, I = idx.search(qvec, n)
    return [ids[i] for i in I[0] if 0 <= i < len(ids)]


def bm25_search(posts: list[dict], query: str, n: int) -> list[str]:
    if not posts:
        return []
    from rank_bm25 import BM25Okapi

    corpus = [_tokenize(p["text"]) for p in posts]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))
    order = np.argsort(scores)[::-1][:n]
    return [posts[i]["id"] for i in order]


def hybrid_search(run_id: str, query: str, k: int = 8, n: int = 20) -> list[str]:
    dense = dense_search(run_id, query, n)
    try:
        sparse = bm25_search(_load_posts(run_id), query, n)
    except (ImportError, RuntimeError):
        sparse = []
    if not sparse:
        return dense[:k]
    return rrf_merge([dense, sparse])[:k]
