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
