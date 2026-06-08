"""Graph nodes: crawl, score, alert, recover, done.

Each node takes the current :class:`AgentState` and returns a partial state
update (LangGraph merges it). The only IO lives in ``crawl`` (delegates to the
existing agent fetch) and ``alert`` (best-effort webhook); both swallow their
errors into state so a failure routes the graph instead of crashing it.

Dependency direction is one-way: this module imports from ``lib.agent`` and
``lib.influence``; those must never import orchestration (circular-import guard).
"""
from __future__ import annotations

import math
import time

import requests

from ..agent import _fetch_all
from ..influence import influence
from ..store import write_json
from . import config
from .state import AgentState


def _squash(raw: float) -> float:
    """Map an unbounded influence score into (0, 1) for threshold comparison."""
    return 1.0 - math.exp(-raw / config.ENGAGEMENT_SQUASH_SCALE)


def crawl(state: AgentState) -> AgentState:
    """Fetch items for the topic across configured sources via the agent loop."""
    topic = state.get("topic", "")
    sources = state.get("sources") or ["facebook"]
    queries = [(topic, s) for s in sources]
    try:
        items = _fetch_all(queries, limit=50, run_id=state.get("run_id"))
        return AgentState(items=items, error=None)
    except Exception as exc:  # connector/agent failure must not crash the graph
        return AgentState(error=str(exc))


def score(state: AgentState) -> AgentState:
    """Score items by squashed influence; gate the alert node on the threshold."""
    now = int(time.time())
    items = state.get("items") or []
    scores = {item.id: _squash(influence(item, now)) for item in items}
    peak = max(scores.values(), default=0.0)
    return AgentState(
        scores=scores,
        should_alert=peak >= config.ENGAGEMENT_THRESHOLD,
    )


def alert(state: AgentState) -> AgentState:
    """Fire the engagement-threshold alert to n8n (best-effort), then continue."""
    scores = state.get("scores") or {}
    top_id, top_score = max(scores.items(), key=lambda kv: kv[1], default=("", 0.0))
    payload: dict[str, str | float | None] = {
        "item_id": top_id,
        "score": top_score,
        "run_id": state.get("run_id"),
    }
    url = f"{config.N8N_WEBHOOK_BASE_URL}/webhook/engagement_alert"
    try:
        requests.post(url, json=payload, timeout=5)
    except requests.RequestException:
        pass  # alerting is non-critical; never block the graph on it
    return AgentState(should_alert=False)


def recover(state: AgentState) -> AgentState:
    """Increment the retry counter, back off, and clear the error for a retry."""
    backoff = config.RETRY_BACKOFF_SECS
    if backoff > 0:
        time.sleep(backoff)
    return AgentState(
        retry_count=state.get("retry_count", 0) + 1,
        error=None,
    )


def done(state: AgentState) -> AgentState:
    """Terminal node: persist a run summary (if run_id) and emit it on state."""
    scores = state.get("scores") or {}
    summary: dict[str, object] = {
        "n_items": len(state.get("items") or []),
        "n_scored": len(scores),
        "max_score": max(scores.values(), default=0.0),
        "retry_count": state.get("retry_count", 0),
        "alerted": state.get("should_alert", False),
        "error": state.get("error"),
    }
    run_id = state.get("run_id")
    if run_id:
        try:
            write_json(run_id, "orchestration_summary.json", summary)
        except OSError:
            pass
    return AgentState(summary=summary)
