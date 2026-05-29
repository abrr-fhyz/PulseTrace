"""Stage 9: influence ranking (engagement + recency decay).

Backs README use-case "Rank influence — finds which posts mattered most".
"""
from __future__ import annotations
import time

import pytest

from lib.connectors.base import Post
from lib.influence import influence, recency, top_n, HALF_LIFE_DAYS

from .conftest import write_stage_artifact


def _mk(pid: str, *, reactions=0, comments=0, shares=0, ts=0) -> Post:
    return Post(id=pid, source="hn", text="x",
                reactions=reactions, comments=comments, shares=shares, ts=ts)


def test_recency_decay_half_life():
    now = 1_000_000_000
    # ts == now -> 1.0
    assert recency(now, now) == pytest.approx(1.0, rel=1e-3)
    # one half-life ago -> 0.5
    one_half = now - int(HALF_LIFE_DAYS * 86400)
    assert recency(one_half, now) == pytest.approx(0.5, rel=1e-3)
    # missing ts -> 0
    assert recency(0, now) == 0.0


def test_influence_weighting_orders_shares_above_reactions():
    """Shares get 3x log weight vs reactions' 1x — a post with shares should
    out-rank a post with the same number of reactions only."""
    a = _mk("a", reactions=100)
    b = _mk("b", shares=100)
    assert influence(b) > influence(a)


def test_top_n_returns_highest_influence_first():
    posts = [
        _mk("low", reactions=1, comments=0, shares=0),
        _mk("mid", reactions=20, comments=10, shares=0),
        _mk("high", reactions=200, comments=80, shares=20),
        _mk("zero"),
    ]
    ranked = top_n(posts, n=3)
    assert [p.id for p in ranked] == ["high", "mid", "low"]
    write_stage_artifact("stage09_influence.json", {
        "scores": [{"id": p.id, "score": round(influence(p), 4)} for p in posts],
        "top3": [p.id for p in ranked],
    })


def test_top_n_truncates_to_n():
    posts = [_mk(f"p{i}", reactions=i) for i in range(10)]
    assert len(top_n(posts, n=4)) == 4
    assert len(top_n(posts, n=20)) == 10
