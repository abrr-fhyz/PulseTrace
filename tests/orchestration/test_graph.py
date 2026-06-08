from __future__ import annotations

import time

import pytest

from lib.connectors.base import Post
from lib.orchestration import config, nodes
from lib.orchestration.graph import (
    _route_after_crawl,
    _route_after_recover,
    _route_after_score,
    build_graph,
)
from lib.orchestration.state import initial_state

pytestmark = pytest.mark.unit

_THREAD = {"configurable": {"thread_id": "test"}}


def _post(pid: str, **kw: int) -> Post:
    return Post(id=pid, source="reddit", text=pid, ts=int(time.time()), **kw)


def test_route_after_crawl() -> None:
    assert _route_after_crawl({"error": "x"}) == "recover"
    assert _route_after_crawl({"error": None}) == "score"


def test_route_after_score() -> None:
    assert _route_after_score({"should_alert": True}) == "alert"
    assert _route_after_score({"should_alert": False}) == "done"


def test_route_after_recover(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "MAX_RETRIES", 3)
    assert _route_after_recover({"retry_count": 2}) == "crawl"
    assert _route_after_recover({"retry_count": 3}) == "done"


def test_happy_path_reaches_done_and_alerts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "ENGAGEMENT_THRESHOLD", 0.5)
    monkeypatch.setattr(
        nodes, "_fetch_all",
        lambda *a, **k: [_post("v", reactions=5000, comments=500, shares=200)],
    )
    posted: list[dict] = []
    monkeypatch.setattr(
        nodes.requests, "post",
        lambda url, json, timeout: posted.append(json),
    )
    graph = build_graph()
    final = graph.invoke(initial_state("t", ["reddit"]), _THREAD)
    assert final["summary"]["n_items"] == 1
    assert posted, "alert webhook should have fired for viral item"


def test_error_path_retries_then_done(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "MAX_RETRIES", 2)
    monkeypatch.setattr(config, "RETRY_BACKOFF_SECS", 0)
    calls = {"n": 0}

    def boom(*a: object, **k: object) -> list[Post]:
        calls["n"] += 1
        raise RuntimeError("down")

    monkeypatch.setattr(nodes, "_fetch_all", boom)
    graph = build_graph()
    final = graph.invoke(initial_state("t", ["reddit"]), _THREAD)
    assert final["retry_count"] == 2
    assert calls["n"] == 2  # initial crawl + 1 retry, then exhausted
    assert "summary" in final
