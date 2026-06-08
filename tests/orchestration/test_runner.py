from __future__ import annotations

import pytest

from lib.orchestration.runner import run_graph_streamed

pytestmark = pytest.mark.unit


class _FakeBus:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.closed: list[str] = []

    def publish(self, run_id: str, event: dict) -> None:
        self.events.append(event)

    def close(self, run_id: str) -> None:
        self.closed.append(run_id)


class _FakeGraph:
    def __init__(self, steps: list[dict]) -> None:
        self._steps = steps

    def stream(self, state: dict, config: dict):  # noqa: ANN001
        yield from self._steps


def _types(bus: _FakeBus) -> list[str]:
    return [e["type"] for e in bus.events]


def test_streams_started_steps_done() -> None:
    bus = _FakeBus()
    graph = _FakeGraph([
        {"crawl": {"items": [object(), object()], "error": None}},
        {"score": {"scores": {"a": 0.9}, "should_alert": True}},
        {"alert": {"should_alert": False}},
        {"done": {"summary": {"n_items": 2, "max_score": 0.9}}},
    ])
    out = run_graph_streamed("t", ["reddit"], "run-1", bus=bus, graph=graph)

    assert _types(bus) == [
        "orch_started", "orch_step", "orch_step", "orch_step", "orch_step", "orch_done"
    ]
    steps = [e for e in bus.events if e["type"] == "orch_step"]
    assert [s["node"] for s in steps] == ["crawl", "score", "alert", "done"]
    assert steps[0]["data"]["items"] == 2
    assert steps[1]["data"]["peak"] == 0.9
    assert steps[1]["data"]["should_alert"] is True
    assert out == {"n_items": 2, "max_score": 0.9}
    assert bus.closed == ["run-1"]


def test_recover_step_reports_retry_count() -> None:
    bus = _FakeBus()
    graph = _FakeGraph([
        {"crawl": {"error": "boom"}},
        {"recover": {"retry_count": 1, "error": None}},
        {"done": {"summary": {"retry_count": 1}}},
    ])
    run_graph_streamed("t", ["reddit"], "r2", bus=bus, graph=graph)
    recover = next(e for e in bus.events if e.get("node") == "recover")
    assert recover["data"]["retry_count"] == 1


def test_stream_exception_still_emits_done() -> None:
    bus = _FakeBus()

    class _Boom:
        def stream(self, state: dict, config: dict):  # noqa: ANN001
            raise RuntimeError("graph blew up")
            yield  # pragma: no cover

    out = run_graph_streamed("t", ["reddit"], "r3", bus=bus, graph=_Boom())
    assert "orch_error" in _types(bus)
    assert _types(bus)[-1] == "orch_done"
    assert out["error"] == "graph blew up"
    assert bus.closed == ["r3"]
