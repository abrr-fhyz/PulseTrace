"""Inference and admin MCP tools, wired to RAG, briefing, stance + schema."""
from __future__ import annotations

from lib.store import read_json, write_json
from lib.rag import ask as rag_ask
from lib.influence import influence, top_n
from lib import stance
from lib.mcp.data_tools import run_status, _post_obj
from lib.mcp.schema import validate_posts


def _consensus_narrative(clusters: list[dict]) -> str:
    pos = neu = neg = 0.0
    for c in clusters:
        s = c.get("sentiment") or {}
        w = len(c.get("members", [])) or 1
        pos += w * float(s.get("pos") or 0)
        neu += w * float(s.get("neu") or 0)
        neg += w * float(s.get("neg") or 0)
    tot = pos + neu + neg or 1.0
    pp, nn, gg = pos / tot, neu / tot, neg / tot
    lean = "positive" if pp > max(nn, gg) else "negative" if gg > max(pp, nn) else "mixed/neutral"
    return (f"Across {len(clusters)} themes the conversation leans {lean} "
            f"(pos={pp:.0%}, neu={nn:.0%}, neg={gg:.0%}).")


def _build_inference(session_id: str) -> dict:
    run = read_json(session_id, "run.json") or {}
    clusters = read_json(session_id, "clusters.json") or []
    posts = read_json(session_id, "posts.json") or []
    topic = run.get("topic", "")

    from lib.briefing import _exec_summary
    try:
        summary = _exec_summary(topic, clusters)
    except Exception:
        summary = ""

    tops = top_n([_post_obj(p) for p in posts], n=5)
    top_users = [t.author for t in tops if t.author]
    return {
        "session_id": session_id,
        "topic": topic,
        "executive_summary": summary,
        "consensus_narrative": _consensus_narrative(clusters),
        "top_users": top_users,
        "n_clusters": len(clusters),
        "n_posts": len(posts),
    }


# --- GROUP C: INFERENCE & ANALYSIS ---

def run_inference(session_id: str) -> dict:
    """Run the conclusion pipeline on a session and persist the inference doc."""
    status = run_status(session_id)
    if status == "unknown":
        return {"session_id": session_id, "status": "unknown", "error": "no such session"}
    clusters = read_json(session_id, "clusters.json")
    if not clusters:
        return {"session_id": session_id, "status": status,
                "error": "no clusters yet — session not ready for inference"}
    doc = _build_inference(session_id)
    write_json(session_id, "inference.json", doc)
    return {"session_id": session_id, "status": "completed", **doc}


def get_inference_result(session_id: str) -> dict:
    """Return the stored conclusion doc for a session (computes it if missing)."""
    if run_status(session_id) == "unknown":
        return {"session_id": session_id, "error": "no such session"}
    doc = read_json(session_id, "inference.json")
    if doc is None:
        return run_inference(session_id)
    return doc


def query_rag(session_id: str, query: str) -> dict:
    """Answer a question grounded only in a session's posts, with cited evidence."""
    if run_status(session_id) == "unknown":
        return {"session_id": session_id, "answer": "No such session.",
                "citations": [], "retrieved": []}
    return rag_ask(session_id, query)


def get_sentiment_breakdown(session_id: str) -> dict:
    """Return overall + per-cluster sentiment distribution with a confidence score."""
    clusters = read_json(session_id, "clusters.json")
    if clusters is None:
        return {"session_id": session_id, "error": "no such session"}
    pos = neu = neg = 0.0
    n = 0
    per: list[dict] = []
    for c in clusters:
        s = c.get("sentiment") or {}
        w = len(c.get("members", []))
        pos += w * float(s.get("pos") or 0)
        neu += w * float(s.get("neu") or 0)
        neg += w * float(s.get("neg") or 0)
        n += w
        per.append({"keyword": c.get("label"), "size": w, "sentiment": s})
    tot = pos + neu + neg or 1.0
    overall = {"pos": round(pos / tot, 3), "neu": round(neu / tot, 3), "neg": round(neg / tot, 3)}
    return {
        "session_id": session_id,
        "overall_sentiment": overall,
        "sample_size": n,
        "confidence": round(min(1.0, n / 50.0), 3),
        "per_keyword": per,
    }


# --- GROUP D: PIPELINE STATE & ADMIN ---

def get_schema_validation_report(session_id: str) -> dict:
    """Validate a session's posts against the post schema; report real pass-rate."""
    posts = read_json(session_id, "posts.json")
    if posts is None:
        return {"session_id": session_id, "error": "no such session"}
    return {"session_id": session_id, **validate_posts(posts)}


def trigger_enrichment_batch(session_id: str) -> dict:
    """Compute engagement_score + per-post sentiment for unenriched posts; persist."""
    posts = read_json(session_id, "posts.json")
    if posts is None:
        return {"session_id": session_id, "error": "no such session"}
    run = read_json(session_id, "run.json") or {}
    topic = run.get("topic", "")
    pending = [p for p in posts if "engagement_score" not in p or "sentiment" not in p]
    if not pending:
        return {"session_id": session_id, "enriched": 0, "total": len(posts),
                "note": "all posts already enriched"}
    for p in pending:
        p["engagement_score"] = round(influence(_post_obj(p)), 3)
    labels = stance.score_batch(topic, [p.get("text", "") for p in pending])
    for p, lab in zip(pending, labels):
        p["sentiment"] = lab
    write_json(session_id, "posts.json", posts)
    return {"session_id": session_id, "enriched": len(pending), "total": len(posts),
            "fields": ["engagement_score", "sentiment"]}


def register(mcp) -> None:
    for fn in (run_inference, get_inference_result, query_rag,
               get_sentiment_breakdown, get_schema_validation_report,
               trigger_enrichment_batch):
        mcp.tool(name=fn.__name__)(fn)
