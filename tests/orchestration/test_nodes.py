from __future__ import annotations

import time

import pytest
import requests

from lib.connectors.base import Post
from lib.orchestration import config, nodes
from lib.orchestration.state import initial_state

pytestmark = pytest.mark.unit


def _post(pid: str, reactions: int = 0, comments: int = 0, shares: int = 0) -> Post:
    return Post(
        id=pid,
        source="reddit",
        text=f"post {pid}",
        ts=int(time.time()),
        reactions=reactions,
        comments=comments,
        shares=shares,
    )


def test_crawl_runs_pipeline_then_loads_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {}
    monkeypatch.setattr(nodes, "run_agent",
                        lambda *a, **k: called.update(close_bus=k.get("close_bus")))
    monkeypatch.setattr(nodes, "load_run_posts", lambda rid: [_post("a"), _post("b")])
    out = nodes.crawl(initial_state("t", ["reddit"], run_id="r"))
    assert [p.id for p in out["items"]] == ["a", "b"]
    assert out["error"] is None
    assert called["close_bus"] is False  # must keep the SSE stream open


def test_crawl_error_captured_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> None:
        raise RuntimeError("pipeline down")

    monkeypatch.setattr(nodes, "run_agent", boom)
    out = nodes.crawl(initial_state("t", ["reddit"], run_id="r"))
    assert "pipeline down" in out["error"]
    assert "items" not in out


def test_load_run_posts_empty_without_run_id() -> None:
    assert nodes.load_run_posts(None) == []


def test_load_run_posts_rebuilds_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nodes, "read_json",
                        lambda rid, name: [_post("x", reactions=3).to_dict()])
    posts = nodes.load_run_posts("r")
    assert posts[0].id == "x" and posts[0].reactions == 3


def test_score_gates_alert_above_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "ENGAGEMENT_THRESHOLD", 0.75)
    st = initial_state("t", ["reddit"])
    st["items"] = [_post("viral", reactions=1000, comments=100, shares=50)]
    out = nodes.score(st)
    assert 0.0 < out["scores"]["viral"] <= 1.0
    assert out["should_alert"] is True


def test_score_no_alert_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "ENGAGEMENT_THRESHOLD", 0.75)
    st = initial_state("t", ["reddit"])
    st["items"] = [_post("quiet")]
    out = nodes.score(st)
    assert out["should_alert"] is False


def test_alert_posts_webhook_and_resets(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, json: dict, timeout: int) -> None:
        captured["url"] = url
        captured["json"] = json

    monkeypatch.setattr(nodes.requests, "post", fake_post)
    st = initial_state("t", ["reddit"], run_id="r1")
    st["scores"] = {"x": 0.9, "y": 0.4}
    out = nodes.alert(st)
    assert captured["json"] == {"item_id": "x", "score": 0.9, "run_id": "r1"}
    assert out["should_alert"] is False


def test_alert_swallows_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> None:
        raise requests.ConnectionError("no n8n")

    monkeypatch.setattr(nodes.requests, "post", boom)
    st = initial_state("t", ["reddit"])
    st["scores"] = {"x": 0.9}
    out = nodes.alert(st)  # must not raise
    assert out["should_alert"] is False


def test_recover_increments_and_clears_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "RETRY_BACKOFF_SECS", 0)
    st = initial_state("t", ["reddit"])
    st["retry_count"] = 1
    st["error"] = "boom"
    out = nodes.recover(st)
    assert out["retry_count"] == 2
    assert out["error"] is None


def test_done_summary_without_run_id() -> None:
    st = initial_state("t", ["reddit"])
    st["items"] = [_post("a")]
    st["scores"] = {"a": 0.6}
    out = nodes.done(st)
    summary = out["summary"]
    assert summary["n_items"] == 1
    assert summary["max_score"] == 0.6
