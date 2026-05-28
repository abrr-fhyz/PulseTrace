from lib.connectors.base import Post
from lib.influence import influence, top_n, recency


def _p(**kw):
    return Post(
        id=kw.get("id", "x"), source="x", text="t",
        ts=kw.get("ts", 0),
        reactions=kw.get("r", 0), comments=kw.get("c", 0), shares=kw.get("s", 0),
    )


def test_more_comments_beats_more_reactions():
    a = _p(id="a", r=1000)
    b = _p(id="b", c=100)
    assert influence(b) > influence(a)


def test_shares_dominate():
    a = _p(id="a", r=1000)
    b = _p(id="b", s=20)
    assert influence(b) > influence(a)


def test_recency_decays():
    now = 1_000_000_000
    fresh = recency(now, now)
    old = recency(now - 30 * 86400, now)
    assert fresh > old


def test_recency_zero_ts():
    assert recency(0) == 0.0


def test_top_n_orders():
    posts = [_p(id=str(i), c=i) for i in range(10)]
    top = top_n(posts, 3)
    assert [p.id for p in top] == ["9", "8", "7"]
