"""Run the orchestration graph and stream per-node progress onto the event bus.

This is the IO/eventing glue that keeps the graph nodes pure: the nodes never
touch the bus; the runner drives ``graph.stream`` and republishes each node's
state delta as an SSE event (reusing the dashboard's ``/events?run_id=`` feed).
"""
from __future__ import annotations

from typing import Any, Protocol

from ..events import BUS
from .graph import build_graph
from .state import AgentState, initial_state


class _Bus(Protocol):
    def publish(self, run_id: str, event: dict[str, Any]) -> None: ...
    def close(self, run_id: str) -> None: ...


class _Graph(Protocol):
    def stream(
        self, state: AgentState, config: dict[str, Any]
    ) -> Any: ...


def _node_view(node: str, acc: dict[str, Any]) -> dict[str, Any]:
    """Project the accumulated state into the fields the UI shows per node."""
    if node == "crawl":
        return {"items": len(acc.get("items") or []), "error": acc.get("error")}
    if node == "score":
        scores = acc.get("scores") or {}
        return {
            "peak": max(scores.values(), default=0.0),
            "n_scored": len(scores),
            "should_alert": bool(acc.get("should_alert")),
        }
    if node == "alert":
        return {"alerted": True}
    if node == "recover":
        return {"retry_count": acc.get("retry_count", 0), "error": acc.get("error")}
    if node == "done":
        return dict(acc.get("summary") or {})
    return {}


def run_graph_streamed(
    topic: str,
    sources: list[str],
    run_id: str,
    bus: _Bus = BUS,
    graph: _Graph | None = None,
) -> dict[str, Any]:
    """Execute the graph, emitting orch_started/orch_step/orch_done on ``bus``."""
    bus.publish(run_id, {
        "type": "orch_started", "run_id": run_id, "topic": topic, "sources": sources,
    })
    g = graph or build_graph()
    acc: dict[str, Any] = {}
    summary: dict[str, Any] = {}
    try:
        for step in g.stream(
            initial_state(topic, sources, run_id),
            {"configurable": {"thread_id": run_id}},
        ):
            for node, update in step.items():
                acc.update(update)
                bus.publish(run_id, {
                    "type": "orch_step", "node": node, "data": _node_view(node, acc),
                })
                if node == "done":
                    summary = dict(update.get("summary") or {})
    except Exception as exc:  # a graph failure must still close the SSE stream
        bus.publish(run_id, {"type": "orch_error", "err": str(exc)})
        summary = {"error": str(exc)}
    bus.publish(run_id, {"type": "orch_done", "summary": summary})
    bus.close(run_id)
    return summary
