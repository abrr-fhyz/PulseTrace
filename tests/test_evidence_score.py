from __future__ import annotations
from lib.connectors.base import Post
from lib import evidence_score as es


def _post(pid, source, ts=0, reactions=0, comments=0, shares=0, text="hello world"):
    return Post(id=pid, source=source, text=text, ts=ts,
                reactions=reactions, comments=comments, shares=shares)


def test_engagement_sums_signals():
    posts = [_post("a", "reddit", reactions=2, comments=3, shares=1),
             _post("b", "hn", reactions=4)]
    assert es.engagement(posts) == 10


def test_source_diversity_counts_distinct():
    posts = [_post("a", "reddit"), _post("b", "reddit"), _post("c", "hn")]
    assert es.source_diversity(posts) == 2


def test_corroboration_norm_one_source_is_low():
    one = [_post("a", "reddit"), _post("b", "reddit")]
    multi = [_post("a", "reddit"), _post("b", "hn"), _post("c", "facebook")]
    assert es.corroboration(one) < es.corroboration(multi)
    assert 0.0 <= es.corroboration(one) <= 1.0
    assert 0.0 <= es.corroboration(multi) <= 1.0


def test_credibility_hn_beats_instagram():
    assert es.credibility([_post("a", "hn")]) > es.credibility([_post("b", "instagram")])


def test_sample_size_norm_bounds():
    assert es.sample_size_norm(0, 10) == 0.0
    assert es.sample_size_norm(10, 10) == 1.0
    assert es.sample_size_norm(5, 0) == 0.0


def test_recency_score_newer_is_higher():
    now = 1_000_000
    old = es.recency_score([_post("a", "hn", ts=now - 30 * 86400)], now)
    new = es.recency_score([_post("b", "hn", ts=now - 1)], now)
    assert new > old


def test_data_quality_rewards_longer_engaged_text():
    thin = [_post("a", "reddit", text="ok")]
    rich = [_post("b", "reddit", text="x" * 400, reactions=20)]
    assert es.data_quality(rich) > es.data_quality(thin)


def test_rank_returns_five_axes_in_unit_range():
    posts = [_post("a", "hn", ts=10, reactions=5, comments=2),
             _post("b", "reddit", ts=20, reactions=1)]
    r = es.rank(posts, max_members=2, now=100)
    assert set(r) == {"credibility", "data_quality", "sample_size", "recency", "corroboration"}
    assert all(0.0 <= v <= 1.0 for v in r.values())


def test_strength_bucket_thresholds():
    weak = {k: 0.1 for k in ("credibility", "data_quality", "sample_size", "recency", "corroboration")}
    strong = {k: 0.9 for k in weak}
    assert es.strength_bucket(weak) == "weak"
    assert es.strength_bucket(strong) == "strong"


def test_blend_is_weighted_and_bounded():
    assert es.blend(0.0, 0.0) == 0.0
    assert es.blend(1.0, 1.0) == 1.0
    mid = es.blend(1.0, 0.0)
    assert 0.0 < mid < 1.0


def test_empty_inputs_return_zeros_not_errors():
    assert es.engagement([]) == 0
    assert es.source_diversity([]) == 0
    assert es.corroboration([]) == 0.0
    r = es.rank([], max_members=0, now=0)
    assert all(v == 0.0 for v in r.values())


def test_category_for_maps_known_and_defaults_social():
    assert es.category_for("hn") == "forums"
    assert es.category_for("facebook") == "social"
    assert es.category_for("unknown") == "social"
