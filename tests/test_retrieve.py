from __future__ import annotations

from lib.retrieve import _tokenize, rrf_merge


def test_tokenize_lowercases_and_splits_on_punct():
    assert _tokenize("Hello, RAG-World! 2026") == ["hello", "rag", "world", "2026"]


def test_tokenize_empty():
    assert _tokenize("") == []


def test_rrf_merge_single_list_preserves_order():
    assert rrf_merge([["a", "b", "c"]]) == ["a", "b", "c"]


def test_rrf_merge_rewards_agreement():
    # "b" is rank 1 in list-1 and rank 0 in list-2 -> highest fused score
    dense = ["a", "b", "c"]
    bm25 = ["b", "d", "a"]
    out = rrf_merge([dense, bm25])
    assert out[0] == "b"
    assert set(out) == {"a", "b", "c", "d"}


def test_rrf_merge_empty():
    assert rrf_merge([]) == []
    assert rrf_merge([[], []]) == []


from lib.retrieve import bm25_search, hybrid_search


def test_bm25_search_ranks_matching_post_first():
    posts = [
        {"id": "p1", "text": "cats are great pets"},
        {"id": "p2", "text": "retrieval augmented generation pipeline"},
        {"id": "p3", "text": "weather is sunny today"},
    ]
    out = bm25_search(posts, "retrieval generation", n=3)
    assert out[0] == "p2"


def test_bm25_search_empty_corpus():
    assert bm25_search([], "anything", n=5) == []


def test_hybrid_search_fuses_dense_and_bm25(monkeypatch):
    import lib.retrieve as R
    monkeypatch.setattr(R, "dense_search", lambda run_id, q, n: ["a", "b", "c"])
    monkeypatch.setattr(R, "_load_posts", lambda run_id: [{"id": "b", "text": "x"}])
    monkeypatch.setattr(R, "bm25_search", lambda posts, q, n: ["b", "d"])
    out = hybrid_search("run1", "q", k=4)
    assert out[0] == "b"  # appears in both -> top


def test_hybrid_search_falls_back_to_dense_when_bm25_unavailable(monkeypatch):
    import lib.retrieve as R
    monkeypatch.setattr(R, "dense_search", lambda run_id, q, n: ["a", "b", "c"])
    monkeypatch.setattr(R, "_load_posts", lambda run_id: [{"id": "a", "text": "x"}])

    def boom(posts, q, n):
        raise RuntimeError("rank_bm25 missing")

    monkeypatch.setattr(R, "bm25_search", boom)
    out = hybrid_search("run1", "q", k=3)
    assert out == ["a", "b", "c"]
