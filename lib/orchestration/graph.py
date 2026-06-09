"""LangGraph state graph wiring the orchestration nodes.

Control flow (replaces the implicit branching of lib/agent.py's while-loop)::

    crawl --success--> score --should_alert--> alert --> done
      |                  |
    error              else
      v                  v
    recover --retry--> crawl
      |
    >= MAX_RETRIES
      v
     done

Persistence
-----------
``build_graph`` compiles with an in-process ``MemorySaver`` — fine for local
dev, but state is LOST on process restart (see known gotchas). To persist
across restarts, swap the checkpointer for a durable one, e.g.::

    from langgraph.checkpoint.sqlite import SqliteSaver
    saver = SqliteSaver.from_conn_string("data/orchestration.sqlite")
    graph = build_graph(checkpointer=saver)

    # or Redis:
    from langgraph.checkpoint.redis import RedisSaver
    graph = build_graph(checkpointer=RedisSaver.from_conn_string(REDIS_URL))

Do NOT wire a remote store here yet — keep MemorySaver as the default.
"""
from __future__ import annotations

from typing import Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from . import config, nodes
from .state import AgentState


def _route_after_crawl(state: AgentState) -> Literal["score", "recover"]:
    """Crawl error routes to recovery; otherwise proceed to scoring."""
    return "recover" if state.get("error") else "score"


def _route_after_score(state: AgentState) -> Literal["alert", "done"]:
    """Alert only when the score node tripped the engagement threshold."""
    return "alert" if state.get("should_alert") else "done"


def _route_after_recover(state: AgentState) -> Literal["crawl", "done"]:
    """Retry the crawl until MAX_RETRIES is exhausted, then give up."""
    if state.get("retry_count", 0) >= config.MAX_RETRIES:
        return "done"
    return "crawl"


def build_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile the orchestration graph; defaults to an in-process MemorySaver."""
    builder: StateGraph = StateGraph(AgentState)
    builder.add_node("crawl", nodes.crawl)
    builder.add_node("score", nodes.score)
    builder.add_node("alert", nodes.alert)
    builder.add_node("recover", nodes.recover)
    builder.add_node("done", nodes.done)

    builder.add_edge(START, "crawl")
    builder.add_conditional_edges(
        "crawl", _route_after_crawl, {"score": "score", "recover": "recover"}
    )
    builder.add_conditional_edges(
        "score", _route_after_score, {"alert": "alert", "done": "done"}
    )
    builder.add_edge("alert", "done")
    builder.add_conditional_edges(
        "recover", _route_after_recover, {"crawl": "crawl", "done": "done"}
    )
    builder.add_edge("done", END)

    return builder.compile(checkpointer=checkpointer or MemorySaver())
