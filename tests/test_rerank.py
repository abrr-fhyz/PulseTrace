"""TDD spec for lib/rerank.py — relevance-dominant ranking + LLM rerank."""
from unittest.mock import patch
from lib.connectors.base import Post
from lib.rerank import final_score, rank_posts, llm_rerank


def _p(text, reactions=0, comments=0, ts=0, **kw):
    return Post(id=text[:12], source="reddit", text=text, reactions=reactions,
                comments=comments, ts=ts, **kw)


def test_ontopic_low_engagement_beats_offtopic_viral():
    # THE regression: engagement must not let off-topic spam win.
    spam = _p("Roast my resume - SDE 2 job hunt 5 yoe", reactions=500, comments=300)
    ontopic = _p("Retrieval augmented generation explained", reactions=2, comments=1)
    ranked = rank_posts("retrieval augmented generation", [spam, ontopic], n=2)
    assert ranked[0].id == ontopic.id


def test_offtopic_is_hard_demoted():
    spam = _p("baking sourdough bread tips", reactions=999)
    s = final_score(spam, relevance=0.0)
    on = final_score(_p("kubernetes operators guide", reactions=1), relevance=0.9)
    assert on > s


def test_relevance_dominates_blend():
    # same engagement, higher relevance must score higher
    p = _p("x", reactions=10, comments=5)
    assert final_score(p, relevance=0.9) > final_score(p, relevance=0.3)


def test_rank_empty_returns_empty():
    assert rank_posts("topic", [], n=5) == []


def test_rank_respects_n():
    posts = [_p(f"retrieval augmented generation note {i}", reactions=i) for i in range(10)]
    assert len(rank_posts("retrieval augmented generation", posts, n=3)) == 3


def test_llm_rerank_orders_by_scores():
    a = _p("alpha about codex pricing")
    b = _p("beta about codex pricing")
    payload = {"scores": [{"id": a.id, "relevance": 20}, {"id": b.id, "relevance": 90}]}
    with patch("lib.rerank.chat_json", return_value=payload):
        ranked = llm_rerank("codex pricing", [a, b], n=2)
    assert ranked[0].id == b.id


def test_llm_rerank_falls_back_on_error():
    spam = _p("resume job hunt", reactions=500)
    ontopic = _p("codex pricing tiers compared", reactions=1)
    with patch("lib.rerank.chat_json", side_effect=RuntimeError("no llm")):
        ranked = llm_rerank("codex pricing", [spam, ontopic], n=2)
    # fallback must still rank on relevance, not crash
    assert ranked[0].id == ontopic.id
