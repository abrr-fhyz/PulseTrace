from unittest.mock import patch

from lib.stance import score_mixed, cluster_sentiments


def test_score_mixed_maps_results_by_index():
    fake = {"items": [{"i": 0, "s": "pos"}, {"i": 1, "s": "neg"}]}
    with patch("lib.stance.chat_json", return_value=fake) as m:
        out = score_mixed([("phones", "love this"), ("phones", "hate it")])
    assert out == ["pos", "neg"]
    # per-post theme must reach the prompt
    user_msg = m.call_args.args[1]
    assert "phones" in user_msg


def test_score_mixed_missing_index_defaults_neutral():
    fake = {"items": [{"i": 0, "s": "pos"}]}
    with patch("lib.stance.chat_json", return_value=fake):
        out = score_mixed([("a", "x"), ("b", "y")])
    assert out == ["pos", "neu"]


def test_score_mixed_llm_failure_all_neutral():
    with patch("lib.stance.chat_json", side_effect=RuntimeError("boom")):
        out = score_mixed([("a", "x"), ("b", "y"), ("c", "z")])
    assert out == ["neu", "neu", "neu"]


def test_score_mixed_empty():
    assert score_mixed([]) == []


def test_cluster_sentiments_aggregates_per_cluster():
    themed = {
        0: ("battery", ["great battery", "amazing life", "lasts forever"]),
        1: ("price", ["too expensive", "overpriced"]),
    }

    def fake_score(items):
        # positive if text mentions 'great/amazing/lasts', else negative
        out = []
        for _theme, text in items:
            out.append("pos" if any(w in text for w in ("great", "amazing", "lasts")) else "neg")
        return out

    with patch("lib.stance.score_mixed", side_effect=fake_score):
        res = cluster_sentiments(themed, batch=2)

    assert set(res) == {0, 1}
    assert res[0]["pos"] == 1.0
    assert res[1]["neg"] == 1.0
    for v in res.values():
        assert abs(v["pos"] + v["neu"] + v["neg"] - 1.0) < 1e-6


def test_cluster_sentiments_empty_cluster_is_neutral():
    with patch("lib.stance.score_mixed", side_effect=AssertionError("should not call")):
        res = cluster_sentiments({0: ("x", [])})
    assert res[0] == {"pos": 0.0, "neu": 1.0, "neg": 0.0}


def test_cluster_sentiments_empty_input():
    assert cluster_sentiments({}) == {}
