"""LangGraph state schema for the orchestration graph.

The five spec fields (items, scores, retry_count, should_alert, error) carry
loop state; topic/sources/run_id are crawl *inputs* and summary is the terminal
output. All are kept in one TypedDict so node functions stay pure — they read
and return only state, never closures or globals.
"""
from __future__ import annotations

from typing import TypedDict

from ..connectors.base import Post

# A crawled item is just a connector Post; aliased so the graph layer has its
# own vocabulary without duplicating the dataclass.
CrawledItem = Post


class AgentState(TypedDict, total=False):
    """Mutable state threaded through every node of the orchestration graph."""

    topic: str
    sources: list[str]
    run_id: str | None
    opinion: str | None

    items: list[CrawledItem]
    scores: dict[str, float]
    retry_count: int
    should_alert: bool
    error: str | None

    summary: dict[str, object]


def initial_state(
    topic: str,
    sources: list[str],
    run_id: str | None = None,
    opinion: str | None = None,
) -> AgentState:
    """Build a fresh state for a run with all loop fields zeroed."""
    return AgentState(
        topic=topic,
        sources=sources,
        run_id=run_id,
        opinion=opinion,
        items=[],
        scores={},
        retry_count=0,
        should_alert=False,
        error=None,
    )
