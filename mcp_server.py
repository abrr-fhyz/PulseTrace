"""PulseTrace MCP server.

Exposes the listening + reasoning pipeline as Model Context Protocol tools so any
MCP client (Claude Desktop, Cursor, custom agents) can drive it. Every tool is
wired to the real per-run store and lib/ functions — no mock data.

Tool groups:
  A crawl control   start/get_status/cancel/list crawl sessions
  B data access     posts by session, post detail, top posts, keyword summary
  C inference       run/get inference, RAG query, sentiment breakdown
  D admin           schema-validation report, enrichment batch
  + coordination    astroturf / coordinated-campaign radar

Run locally (stdio):
    .venv/bin/python mcp_server.py
HTTP/SSE for remote agents:
    PULSETRACE_MCP_TRANSPORT=streamable-http .venv/bin/python mcp_server.py
"""
from __future__ import annotations
import json
import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from lib.store import ROOT, read_json
from lib.coordination import detect_campaigns
from lib.mcp import data_tools, intelligence_tools
from lib.mcp.data_tools import run_status

load_dotenv()

mcp = FastMCP("PulseTrace")

data_tools.register(mcp)
intelligence_tools.register(mcp)


@mcp.tool(name="detect_coordination")
def detect_coordination(session_id: str, min_authors: int = 3) -> dict:
    """Detect coordinated / astroturf campaigns in a session.

    Near-identical posts from >= min_authors distinct accounts in a tight window
    are flagged and scored. Leads for investigation, not verdicts.
    """
    posts = read_json(session_id, "posts.json")
    if posts is None:
        return {"session_id": session_id, "campaigns": [], "error": "no such session"}
    camps = detect_campaigns(posts, min_authors=min_authors)
    return {
        "session_id": session_id,
        "n_campaigns": len(camps),
        "campaigns": [{
            "score": round(c.score, 3),
            "n_authors": c.n_authors,
            "n_copies": c.n_copies,
            "span_seconds": c.span_seconds,
            "authors": c.authors,
            "sample_text": c.sample_text,
            "examples": c.examples,
        } for c in camps],
    }


@mcp.resource("pulsetrace://sessions")
def list_sessions() -> str:
    """List all crawl sessions (most recent first)."""
    rows: list[dict] = []
    if ROOT.exists():
        for d in ROOT.iterdir():
            if not d.is_dir():
                continue
            run = read_json(d.name, "run.json") or {}
            rows.append({
                "session_id": d.name,
                "topic": run.get("topic"),
                "status": run_status(d.name),
                "started_at": run.get("started_at"),
                "posts": (run.get("metrics") or {}).get("posts"),
            })
    rows.sort(key=lambda r: r.get("started_at") or 0, reverse=True)
    return json.dumps(rows, indent=2)


if __name__ == "__main__":
    transport = os.environ.get("PULSETRACE_MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)
