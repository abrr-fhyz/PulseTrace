from __future__ import annotations

import pytest

from lib import replay


def _run() -> dict:
    return {
        "id": "r1",
        "topic": "coffee",
        "queries": [
            {"q": "best coffee", "source": "facebook", "iter": 1},
            {"q": "coffee health", "source": "facebook", "iter": 1},
            {"q": "espresso tips", "source": "facebook", "iter": 2},
            {"q": "cold brew", "source": "facebook", "iter": 3},
        ],
    }


def _posts() -> list[dict]:
    # one post per query, plus one undeterminable post (query not in run)
    return [
        {"id": "p1", "text": "a", "raw": {"query": "best coffee", "shot": "q0_s0_x.png"}},
        {"id": "p2", "text": "b", "raw": {"query": "coffee health", "shot": "q1_s0_x.png"}},
        {"id": "p3", "text": "c", "raw": {"query": "espresso tips", "shot": "q0_s0_x.png"}},
        {"id": "p4", "text": "d", "raw": {"query": "cold brew", "shot": "q0_s0_x.png"}},
        {"id": "p5", "text": "e", "raw": {"query": "mystery", "shot": "q9_s0_x.png"}},
    ]


def test_max_iter_basic():
    assert replay.max_iter(_run()) == 3


def test_max_iter_empty_defaults_to_one():
    assert replay.max_iter({}) == 1
    assert replay.max_iter({"queries": []}) == 1


def test_posts_through_iter_one_only():
    got = replay.posts_through_iter(_posts(), 1, run=_run())
    ids = {p["id"] for p in got}
    # iter-1 queries -> p1, p2; undeterminable p5 treated as iter 1
    assert ids == {"p1", "p2", "p5"}


def test_posts_through_iter_two():
    got = replay.posts_through_iter(_posts(), 2, run=_run())
    ids = {p["id"] for p in got}
    assert ids == {"p1", "p2", "p3", "p5"}


def test_posts_through_iter_all():
    got = replay.posts_through_iter(_posts(), 3, run=_run())
    assert {p["id"] for p in got} == {"p1", "p2", "p3", "p4", "p5"}


def test_posts_through_iter_beyond_max():
    got = replay.posts_through_iter(_posts(), 99, run=_run())
    assert len(got) == 5


def test_posts_through_iter_empty_inputs():
    assert replay.posts_through_iter([], 1, run=_run()) == []
    # no run -> everything falls back to iter 1
    got = replay.posts_through_iter(_posts(), 1, run=None)
    assert len(got) == 5


def test_stringified_raw_is_parsed():
    posts = [{"id": "s1", "text": "x",
              "raw": "{'query': 'espresso tips', 'shot': 'q0_s0.png'}"}]
    at1 = replay.posts_through_iter(posts, 1, run=_run())
    at2 = replay.posts_through_iter(posts, 2, run=_run())
    assert at1 == []  # espresso tips is iter 2
    assert len(at2) == 1


def test_frame_shape_and_monotonic():
    run = _run()
    posts = _posts()

    def fake_read(run_id, name):
        if name == "run.json":
            return run
        if name == "posts.json":
            return posts
        return None

    counts = []
    for it in range(1, replay.max_iter(run) + 1):
        fr = replay.frame("r1", it, read=fake_read)
        assert fr["iter"] == it
        assert fr["n_posts"] == len(fr["posts"])
        assert all(qd["iter"] <= it for qd in fr["queries"])
        counts.append(fr["n_posts"])

    assert counts == sorted(counts), "n_posts must be non-decreasing"


def test_frame_missing_run_is_graceful():
    def empty_read(run_id, name):
        return None

    fr = replay.frame("nope", 3, read=empty_read)
    assert fr["iter"] == 3
    assert fr["n_posts"] == 0
    assert fr["posts"] == []
    assert fr["queries"] == []
