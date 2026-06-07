"""PulseTrace MCP server.

Exposes the moat — agentic multi-source analysis, FB vision-OCR corpus, cited
RAG Q&A, and the coordination/astroturf radar — as Model Context Protocol tools
so any MCP client (Claude Desktop, Cursor, custom agents) can call them.

Run locally (stdio):
    .venv/bin/python mcp_server.py
HTTP/SSE for remote agents:
    PULSETRACE_MCP_TRANSPORT=streamable-http .venv/bin/python mcp_server.py
"""
from __future__ import annotations
import json
import os
import threading

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from lib.agent import run_agent, SOURCES
from lib.store import ROOT, read_json
from lib.rag import ask as rag_ask
from lib.coordination import detect_campaigns

load_dotenv()

mcp = FastMCP("PulseTrace")


def _run_status(run_id: str) -> str:
    run = read_json(run_id, "run.json")
    if run and run.get("finished_at"):
        return "completed"
    if read_json(run_id, "clusters.json") is not None:
        return "running"
    if (ROOT / run_id).exists():
        return "pending"
    return "unknown"


@mcp.tool()
def analyze_topic(topic: str, sources: list[str] | None = None) -> dict:
    """Launch an agentic analysis run for a topic across social sources.

    Fetches, clusters, labels and scores sentiment across the given sources
    (reddit, hn, facebook, x, instagram). Long-running: returns a run_id
    immediately; poll get_run(run_id) until status == "completed".
    """
    picked = [s for s in (sources or ["reddit", "hn"]) if s in SOURCES]
    if not picked:
        picked = ["reddit", "hn"]
    box: dict[str, str] = {}

    def go() -> None:
        try:
            run_agent(topic, picked, run_id=box["run_id"])
        except Exception:
            pass

    from lib.store import new_run_id
    box["run_id"] = new_run_id()
    threading.Thread(target=go, daemon=True).start()
    return {
        "run_id": box["run_id"],
        "topic": topic,
        "sources": picked,
        "status": "started",
        "hint": "poll get_run(run_id) until status == 'completed'",
    }


@mcp.tool()
def get_run(run_id: str) -> dict:
    """Get status and results (clusters, sentiment, metrics) for a run."""
    status = _run_status(run_id)
    if status == "unknown":
        return {"run_id": run_id, "status": "unknown", "error": "no such run"}
    run = read_json(run_id, "run.json") or {}
    clusters = read_json(run_id, "clusters.json") or []
    return {
        "run_id": run_id,
        "status": status,
        "topic": run.get("topic"),
        "sources": run.get("sources"),
        "stop_reason": run.get("stop_reason"),
        "metrics": run.get("metrics"),
        "clusters": [
            {
                "id": c["id"],
                "label": c.get("label"),
                "n": len(c.get("members", [])),
                "sentiment": c.get("sentiment"),
            }
            for c in clusters
        ],
    }


@mcp.tool()
def ask_corpus(run_id: str, question: str) -> dict:
    """Ask a question answered only from a run's posts, with cited evidence."""
    if _run_status(run_id) == "unknown":
        return {"answer": "No such run.", "citations": [], "retrieved": []}
    return rag_ask(run_id, question)


@mcp.tool()
def detect_coordination(run_id: str, min_authors: int = 3) -> dict:
    """Detect coordinated / astroturf campaigns in a run.

    Near-identical posts from >= min_authors distinct accounts in a tight window
    are flagged and scored. These are leads for investigation, not verdicts.
    """
    posts = read_json(run_id, "posts.json")
    if posts is None:
        return {"run_id": run_id, "campaigns": [], "error": "no posts for run"}
    camps = detect_campaigns(posts, min_authors=min_authors)
    return {
        "run_id": run_id,
        "n_campaigns": len(camps),
        "campaigns": [
            {
                "score": round(c.score, 3),
                "n_authors": c.n_authors,
                "n_copies": c.n_copies,
                "span_seconds": c.span_seconds,
                "authors": c.authors,
                "sample_text": c.sample_text,
                "examples": c.examples,
            }
            for c in camps
        ],
    }


@mcp.resource("pulsetrace://runs")
def list_runs() -> str:
    """List all analysis runs (most recent first)."""
    rows: list[dict] = []
    if ROOT.exists():
        for d in ROOT.iterdir():
            if not d.is_dir():
                continue
            run = read_json(d.name, "run.json") or {}
            rows.append({
                "run_id": d.name,
                "topic": run.get("topic"),
                "status": _run_status(d.name),
                "started_at": run.get("started_at"),
                "posts": (run.get("metrics") or {}).get("posts"),
            })
    rows.sort(key=lambda r: r.get("started_at") or 0, reverse=True)
    return json.dumps(rows, indent=2)


if __name__ == "__main__":
    transport = os.environ.get("PULSETRACE_MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)
