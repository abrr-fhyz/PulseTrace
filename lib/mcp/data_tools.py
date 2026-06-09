"""Crawl-control and data-access MCP tools, wired to the run store + pipeline."""
from __future__ import annotations
import threading

from lib.store import ROOT, read_json, new_run_id, request_cancel
from lib.agent import run_agent, SOURCES
from lib.influence import influence, top_n
from lib.connectors.base import Post

DEFAULT_SOURCES = ["reddit", "hn"]


def run_status(run_id: str) -> str:
    run = read_json(run_id, "run.json")
    if run and run.get("finished_at"):
        return "cancelled" if run.get("stop_reason") == "cancelled" else "completed"
    if read_json(run_id, "clusters.json") is not None:
        return "running"
    if (ROOT / run_id).exists():
        return "pending"
    return "unknown"


def _post_obj(p: dict) -> Post:
    fields = {f: p.get(f) for f in (
        "id", "source", "text", "author", "url", "ts",
        "reactions", "comments", "shares", "raw")}
    fields["raw"] = fields.get("raw") or {}
    return Post(**fields)


def _post_view(p: dict) -> dict:
    return {
        "id": p.get("id"),
        "source": p.get("source"),
        "text": p.get("text"),
        "author": p.get("author"),
        "url": p.get("url"),
        "ts": p.get("ts"),
        "reactions": p.get("reactions"),
        "comments": p.get("comments"),
        "shares": p.get("shares"),
        "engagement_score": round(influence(_post_obj(p)), 3),
    }


# --- GROUP A: CRAWL CONTROL ---

def start_crawl_session(topic: str, sources: list[str] | None = None) -> dict:
    """Start an agentic crawl+analysis run for a topic across social sources.

    Long-running: returns a session_id immediately and runs in the background.
    Poll get_crawl_status(session_id) until status == 'completed'.
    """
    picked = [s for s in (sources or DEFAULT_SOURCES) if s in SOURCES] or DEFAULT_SOURCES
    run_id = new_run_id()

    def go() -> None:
        try:
            run_agent(topic, picked, run_id=run_id)
        except Exception:
            pass

    threading.Thread(target=go, daemon=True).start()
    return {
        "session_id": run_id,
        "topic": topic,
        "sources": picked,
        "status": "started",
        "hint": "poll get_crawl_status(session_id) until status == 'completed'",
    }


def get_crawl_status(session_id: str) -> dict:
    """Return live state of a crawl session: status, posts collected, iterations."""
    status = run_status(session_id)
    if status == "unknown":
        return {"session_id": session_id, "status": "unknown", "error": "no such session"}
    run = read_json(session_id, "run.json") or {}
    posts = read_json(session_id, "posts.json") or []
    metrics = run.get("metrics") or {}
    iters = len({q.get("iter") for q in (run.get("queries") or []) if q.get("iter")})
    return {
        "session_id": session_id,
        "status": status,
        "posts_collected": metrics.get("posts", len(posts)),
        "clusters": metrics.get("clusters"),
        "iterations": iters or None,
        "stop_reason": run.get("stop_reason"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
    }


def cancel_crawl_session(session_id: str) -> dict:
    """Request cooperative cancellation of an active crawl session.

    The agent loop stops at its next iteration checkpoint and finalizes with
    stop_reason='cancelled'.
    """
    status = run_status(session_id)
    if status == "unknown":
        return {"session_id": session_id, "status": "unknown", "error": "no such session"}
    if status in ("completed", "cancelled"):
        return {"session_id": session_id, "status": status, "cancelled": False,
                "note": "session already finished"}
    request_cancel(session_id)
    return {"session_id": session_id, "status": "cancelling", "cancelled": True,
            "note": "agent stops at next iteration checkpoint"}


def list_crawl_sessions(page: int = 1, limit: int = 10) -> dict:
    """Return a paginated index of all crawl sessions, newest first."""
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
                "posts_count": (run.get("metrics") or {}).get("posts"),
                "started_at": run.get("started_at"),
            })
    rows.sort(key=lambda r: r.get("started_at") or 0, reverse=True)
    page = max(1, page)
    limit = max(1, limit)
    start = (page - 1) * limit
    return {"page": page, "limit": limit, "total": len(rows),
            "sessions": rows[start:start + limit]}


# --- GROUP B: DATA ACCESS ---

def get_posts_by_session(session_id: str, keyword: str | None = None,
                         min_engagement: float = 0.0) -> dict:
    """Return enriched posts for a session, optionally filtered by keyword/engagement."""
    posts = read_json(session_id, "posts.json")
    if posts is None:
        return {"session_id": session_id, "count": 0, "posts": [], "error": "no such session"}
    kw = (keyword or "").lower()
    out: list[dict] = []
    for p in posts:
        if kw and kw not in (p.get("text") or "").lower():
            continue
        view = _post_view(p)
        if view["engagement_score"] < min_engagement:
            continue
        out.append(view)
    return {"session_id": session_id, "count": len(out), "posts": out}


def get_post_detail(post_id: str, session_id: str | None = None) -> dict:
    """Return the full record (incl. raw) for a single post, by id."""
    def find(rid: str) -> dict | None:
        for p in (read_json(rid, "posts.json") or []):
            if p.get("id") == post_id:
                return p
        return None

    if session_id:
        p = find(session_id)
        if p is None:
            return {"post_id": post_id, "error": "no such post in session"}
        return {"session_id": session_id, **p,
                "engagement_score": round(influence(_post_obj(p)), 3)}
    if ROOT.exists():
        for d in ROOT.iterdir():
            if not d.is_dir():
                continue
            p = find(d.name)
            if p is not None:
                return {"session_id": d.name, **p,
                        "engagement_score": round(influence(_post_obj(p)), 3)}
    return {"post_id": post_id, "error": "no such post"}


def get_top_posts(session_id: str, limit: int = 5) -> dict:
    """Return the top posts in a session ranked by influence (engagement+recency)."""
    posts = read_json(session_id, "posts.json")
    if posts is None:
        return {"session_id": session_id, "count": 0, "posts": [], "error": "no such session"}
    objs = [_post_obj(p) for p in posts]
    tops = top_n(objs, n=max(1, limit))
    return {
        "session_id": session_id,
        "count": len(tops),
        "posts": [{
            "id": t.id, "source": t.source, "author": t.author, "text": t.text,
            "url": t.url, "engagement_score": round(influence(t), 3),
        } for t in tops],
    }


def get_keyword_summary(session_id: str) -> dict:
    """Return per-cluster stats: label, post volume, avg engagement, sentiment dist."""
    clusters = read_json(session_id, "clusters.json")
    if clusters is None:
        return {"session_id": session_id, "keywords": [], "error": "no such session"}
    by_id = {p["id"]: p for p in (read_json(session_id, "posts.json") or [])}
    items: list[dict] = []
    for c in clusters:
        members = c.get("members", [])
        engs = [influence(_post_obj(by_id[m])) for m in members if m in by_id]
        avg = round(sum(engs) / len(engs), 3) if engs else 0.0
        items.append({
            "keyword": c.get("label"),
            "post_volume": len(members),
            "average_engagement": avg,
            "sentiment_distribution": c.get("sentiment", {}),
        })
    return {"session_id": session_id, "keywords": items}


def register(mcp) -> None:
    for fn in (start_crawl_session, get_crawl_status, cancel_crawl_session,
               list_crawl_sessions, get_posts_by_session, get_post_detail,
               get_top_posts, get_keyword_summary):
        mcp.tool(name=fn.__name__)(fn)
