from __future__ import annotations

from lib.wordcloud import cluster_terms, run_wordclouds


def test_empty_texts_returns_empty_list():
    assert cluster_terms([]) == []
    assert cluster_terms(["", "   "]) == []


def test_empty_clusters_returns_empty_dict():
    assert run_wordclouds([], {}) == {}


def test_single_cluster_returns_terms():
    texts = ["climate change policy reform", "carbon emissions policy reform"]
    terms = cluster_terms(texts, top_k=5)
    assert terms, "expected non-empty terms"
    vocab = {t for t, _ in terms}
    assert "policy" in vocab
    assert all(len(t) >= 3 for t in vocab)
    assert "the" not in vocab and "and" not in vocab


def test_weights_descending():
    terms = cluster_terms(["alpha alpha alpha beta gamma"], top_k=5)
    weights = [w for _, w in terms]
    assert weights == sorted(weights, reverse=True)


def test_top_k_caps_results():
    text = " ".join(f"term{i}" for i in range(50))
    terms = cluster_terms([text], top_k=7)
    assert len(terms) <= 7


def test_distinguishing_terms_outrank_shared_terms():
    clusters = [
        {"id": 0, "members": ["a", "b"]},
        {"id": 1, "members": ["c", "d"]},
    ]
    posts_by_id = {
        "a": {"id": "a", "text": "election voting ballot shared common word"},
        "b": {"id": "b", "text": "election voting candidate shared common word"},
        "c": {"id": "c", "text": "football soccer goal shared common word"},
        "d": {"id": "d", "text": "football soccer match shared common word"},
    }
    out = run_wordclouds(clusters, posts_by_id, top_k=10)
    assert set(out.keys()) == {0, 1}

    def rank(terms: list[tuple[str, float]], word: str) -> float:
        for t, w in terms:
            if t == word:
                return w
        return 0.0

    c0 = out[0]
    assert rank(c0, "election") > rank(c0, "shared")
    assert rank(c0, "voting") > rank(c0, "common")
    c1 = out[1]
    assert rank(c1, "football") > rank(c1, "shared")


def test_cluster_with_no_member_texts_yields_empty_terms():
    clusters = [
        {"id": 0, "members": ["a"]},
        {"id": 1, "members": ["missing"]},
    ]
    posts_by_id = {"a": {"id": "a", "text": "real content words here"}}
    out = run_wordclouds(clusters, posts_by_id, top_k=5)
    assert out[1] == []
    assert out[0]
