#!/usr/bin/env python3
"""PulseTrace v2 Flask server: agent runs, SSE, graph, RAG.

Legacy v1 endpoints (/status, /run-command) preserved.
"""
from __future__ import annotations
import os
import threading
import time
import subprocess
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import numpy as np
from dotenv import load_dotenv

load_dotenv()
from lib.keys import load as _load_api_keys
_load_api_keys()

import re as _re

from lib.agent import run_agent
from lib.orchestration.runner import run_graph_streamed
from lib.briefing import build as build_briefing
from lib.events import BUS, sse_format
from lib.store import read_json, new_run_id, run_dir, ROOT
from lib.replay import frame as replay_frame, max_iter as replay_max_iter
from lib.rag import ask as rag_ask
from lib import backend, fb_cookies, docs as docs_mod
from lib import docs_content
from lib import chat_store, chat_memory, chat_engine


app = Flask(__name__)
CORS(app)


BYOK_PROVIDER_REGISTRY = [
    {"id": "gemini",      "label": "Google Gemini",        "enabled": True,
     "key_hint": "AIza... or AQ.Ab...", "key_env": "GEMINI_API_KEY",
     "validate_url": "https://generativelanguage.googleapis.com/v1beta/models?key={key}"},
    {"id": "groq",        "label": "Groq",                 "enabled": False,
     "key_hint": "gsk_...", "key_env": "GROQ_API_KEY"},
    {"id": "openrouter",  "label": "OpenRouter",           "enabled": False,
     "key_hint": "sk-or-...", "key_env": "OPENROUTER_API_KEY"},
    {"id": "llm7",        "label": "LLM7",                 "enabled": False,
     "key_hint": "base64-ish token", "key_env": "LLM7_API_KEY"},
    {"id": "huggingface", "label": "Hugging Face",         "enabled": False,
     "key_hint": "hf_...", "key_env": "HUGGINGFACE_TOKEN"},
    {"id": "pollen",      "label": "Pollinations",         "enabled": False,
     "key_hint": "sk_...", "key_env": "POLLEN_API_KEY"},
    {"id": "ollama",      "label": "Ollama (local/cloud)", "enabled": False,
     "key_hint": "optional", "key_env": "OLLAMA_API_KEY"},
]
_BYOK_BY_ID = {p["id"]: p for p in BYOK_PROVIDER_REGISTRY}


def _byok_apply(byok: dict | None) -> dict[str, str]:
    """Inject BYOK key into os.environ for the run thread. Returns prior values
    so the caller can restore them after. Returns {} if no byok."""
    if not byok:
        return {}
    pid = (byok.get("provider") or "").lower().strip()
    key = (byok.get("api_key") or "").strip()
    spec = _BYOK_BY_ID.get(pid)
    if not spec or not spec["enabled"] or not key:
        return {}
    prior: dict[str, str] = {
        "PULSETRACE_BACKEND": os.environ.get("PULSETRACE_BACKEND", ""),
        spec["key_env"]: os.environ.get(spec["key_env"], ""),
    }
    os.environ["PULSETRACE_BACKEND"] = pid
    os.environ[spec["key_env"]] = key
    if pid == "gemini":
        prior["GOOGLE_API_KEY"] = os.environ.get("GOOGLE_API_KEY", "")
        os.environ["GOOGLE_API_KEY"] = key
    return prior


def _byok_restore(prior: dict[str, str]) -> None:
    for k, v in prior.items():
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


@app.route("/")
def index():
    return render_template("index.html")


def _docs_context():
    return dict(
        pitch=docs_content.PITCH,
        team=docs_content.TEAM,
        features=docs_content.FEATURES,
        roadmap=docs_content.ROADMAP,
        stack=docs_content.STACK,
        apis_exposed=docs_content.APIS_EXPOSED,
        apis_consumed=docs_content.APIS_CONSUMED,
        architecture=docs_content.ARCHITECTURE_MERMAID,
        dataflow=docs_content.DATA_FLOW_MERMAID,
        data_layer=docs_content.DATA_LAYER,
        ai_layer=docs_content.AI_LAYER,
        performance=docs_content.PERFORMANCE,
        security=docs_content.SECURITY,
        analytics=docs_content.ANALYTICS,
        changelog=docs_content.CHANGELOG,
        stats=docs_mod.live_stats(),
        cfg=docs_mod.load_config(),
    )


@app.route("/docs")
def docs_page():
    status = docs_mod.access_status()
    if not status["allowed"]:
        return render_template(
            "docs_blocked.html",
            reason=status["reason"],
            start=status.get("start", ""),
            end=status.get("end", ""),
        ), 403
    return render_template("docs.html", **_docs_context())


@app.route("/docs/admin", methods=["GET"])
def docs_admin():
    cfg = docs_mod.load_config()
    return render_template(
        "docs_admin.html",
        cfg=cfg,
        access=docs_mod.access_status(cfg),
        message=request.args.get("message"),
        error=request.args.get("error"),
    )


@app.route("/docs/admin/save", methods=["POST"])
def docs_admin_save():
    token = (request.form.get("token") or "").strip()
    if token != docs_mod.admin_token():
        cfg = docs_mod.load_config()
        return render_template(
            "docs_admin.html", cfg=cfg, access=docs_mod.access_status(cfg),
            error="Invalid admin token.", message=None,
        ), 403
    cfg = docs_mod.load_config()
    cfg["enabled"] = bool(request.form.get("enabled"))
    cfg["override_always_on"] = bool(request.form.get("override_always_on"))
    start = (request.form.get("start") or "").strip()
    end = (request.form.get("end") or "").strip()
    if start:
        cfg["start"] = start
    if end:
        cfg["end"] = end
    docs_mod.save_config(cfg)
    return render_template(
        "docs_admin.html", cfg=cfg, access=docs_mod.access_status(cfg),
        message="Saved.", error=None,
    )


@app.route("/docs/export/markdown")
def docs_export_md():
    status = docs_mod.access_status()
    if not status["allowed"]:
        return "Docs not available.", 403
    ctx = _docs_context()
    p, team, features, roadmap, stack = ctx["pitch"], ctx["team"], ctx["features"], ctx["roadmap"], ctx["stack"]
    lines = [
        "# PulseTrace", f"_{p['tagline']}_", "",
        "## Problem", p["problem"], "",
        "## Solution", p["solution"], "",
        "## Why Now", *[f"- {w}" for w in p["why_now"]], "",
        "## Demo", p["demo"], "",
        "## Market", p["market"], "",
        "## Business Model", p["business_model"], "",
        "## Traction", *[f"- {t}" for t in p["traction"]], "",
        "## Competition", p["competition"], "",
        "## Unique Advantage", p["advantage"], "",
        "## Go-To-Market", p["gtm"], "",
        f"## Team — {team['name']}",
    ]
    for m in team["members"]:
        lines.append(f"- **{m['name']}** — {m['role']} — {m['email']}")
    lines += ["", "## Vision", p["vision"], "", "## Feature Matrix"]
    for f in features:
        lines.append(f"- [{f['status']}] **{f['name']}** — {f['detail']}")
    lines += ["", "## Roadmap"]
    for k in ("short", "mid", "long"):
        lines.append(f"### {k.title()}")
        lines += [f"- {r}" for r in roadmap[k]]
    lines += ["", "## Stack"]
    for layer, items in stack.items():
        lines.append(f"- **{layer}**: {', '.join(items)}")
    lines += ["", "## Architecture", "```mermaid", ctx["architecture"], "```", ""]
    lines += ["## Data Flow", "```mermaid", ctx["dataflow"], "```", ""]
    lines += ["## Changelog"]
    for d, t in ctx["changelog"]:
        lines.append(f"- **{d}** — {t}")
    body = "\n".join(lines)
    return Response(body, mimetype="text/markdown",
                    headers={"Content-Disposition": "attachment; filename=pulsetrace-docs.md"})


@app.route("/run", methods=["POST"])
def start_run():
    data = request.get_json(force=True, silent=True) or {}
    topic = (data.get("topic") or "").strip()
    sources = data.get("sources") or ["facebook"]
    byok = data.get("byok") or None
    if not topic:
        return jsonify({"error": "topic required"}), 400

    if byok:
        pid = (byok.get("provider") or "").lower().strip()
        spec = _BYOK_BY_ID.get(pid)
        if not spec:
            return jsonify({"error": f"unknown provider {pid!r}"}), 400
        if not spec["enabled"]:
            return jsonify({"error": f"{spec['label']} is not yet wired "
                            "(Gemini-only beta)"}), 400
        if not (byok.get("api_key") or "").strip():
            return jsonify({"error": "api_key required when byok set"}), 400

    opinion = (data.get("opinion") or "").strip() or None
    run_id = new_run_id()

    def go():
        prior = _byok_apply(byok)
        try:
            run_agent(topic, sources, run_id=run_id, opinion=opinion)
        except Exception as e:
            BUS.publish(run_id, {"type": "error", "err": str(e)})
        finally:
            _byok_restore(prior)

    threading.Thread(target=go, daemon=True).start()
    return jsonify({"run_id": run_id, "byok": bool(byok)})


@app.route("/api/agent/run", methods=["POST"])
def start_orchestration_run():
    """Run the LangGraph orchestration graph (wraps the full agent pipeline and
    adds engagement alerting, retry/recovery, and scheduling). Progress streams
    over /events; the same run_id drives the dashboard's pipeline/graph views."""
    data = request.get_json(force=True, silent=True) or {}
    topic = (data.get("topic") or "").strip()
    sources = data.get("sources") or ["reddit"]
    opinion = (data.get("opinion") or "").strip() or None
    byok = data.get("byok") or None
    if not topic:
        return jsonify({"error": "topic required"}), 400

    if byok:
        pid = (byok.get("provider") or "").lower().strip()
        spec = _BYOK_BY_ID.get(pid)
        if not spec:
            return jsonify({"error": f"unknown provider {pid!r}"}), 400
        if not spec["enabled"]:
            return jsonify({"error": f"{spec['label']} is not yet wired "
                            "(Gemini-only beta)"}), 400
        if not (byok.get("api_key") or "").strip():
            return jsonify({"error": "api_key required when byok set"}), 400

    run_id = new_run_id()

    def go() -> None:
        prior = _byok_apply(byok)
        try:
            run_graph_streamed(topic, sources, run_id, opinion=opinion)
        except Exception as e:
            BUS.publish(run_id, {"type": "orch_error", "err": str(e)})
            BUS.close(run_id)
        finally:
            _byok_restore(prior)

    threading.Thread(target=go, daemon=True).start()
    return jsonify({"run_id": run_id, "byok": bool(byok)})


@app.route("/providers")
def list_providers():
    """Public registry of providers offered in the BYOK UI."""
    return jsonify({
        "providers": [
            {"id": p["id"], "label": p["label"], "enabled": p["enabled"],
             "key_hint": p["key_hint"]}
            for p in BYOK_PROVIDER_REGISTRY
        ],
        "default_provider": "gemini",
    })


@app.route("/byok/validate", methods=["POST"])
def byok_validate():
    """Ping the provider's API with the supplied key. Returns {ok:true} or
    {ok:false, error:...}. Only Gemini is wired right now; others reject."""
    data = request.get_json(force=True, silent=True) or {}
    pid = (data.get("provider") or "").lower().strip()
    key = (data.get("api_key") or "").strip()
    spec = _BYOK_BY_ID.get(pid)
    if not spec:
        return jsonify({"ok": False, "error": f"unknown provider {pid!r}"}), 400
    if not spec["enabled"]:
        return jsonify({"ok": False, "error": f"{spec['label']} not yet wired "
                        "(Gemini-only beta)"}), 400
    if not key:
        return jsonify({"ok": False, "error": "api_key required"}), 400

    import requests as _rq
    try:
        url = spec["validate_url"].format(key=key)
        r = _rq.get(url, timeout=10)
        if r.status_code == 200:
            return jsonify({"ok": True, "provider": pid})
        try:
            msg = r.json().get("error", {}).get("message", r.text[:200])
        except Exception:
            msg = r.text[:200]
        return jsonify({"ok": False, "error": f"HTTP {r.status_code}: {msg}"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.route("/shots/<run_id>")
def shots_list(run_id):
    from pathlib import Path as _P
    base = _P("data/runs") / run_id / "shots"
    if not base.exists():
        return jsonify({"run_id": run_id, "iters": []})
    iters = []
    for it in sorted(base.iterdir()):
        if not it.is_dir():
            continue
        files = sorted([f.name for f in it.iterdir()
                        if f.is_file() and f.suffix.lower() == ".png"])
        if files:
            iters.append({"iter": it.name, "shots": files,
                          "count": len(files)})
    return jsonify({"run_id": run_id, "iters": iters})


@app.route("/shots/<run_id>/<iter_name>/<filename>")
def shots_file(run_id, iter_name, filename):
    from pathlib import Path as _P
    if not filename.endswith(".png") or "/" in filename or ".." in filename:
        return jsonify({"error": "bad filename"}), 400
    if "/" in iter_name or ".." in iter_name:
        return jsonify({"error": "bad iter"}), 400
    p = _P("data/runs") / run_id / "shots" / iter_name / filename
    if not p.exists():
        return jsonify({"error": "not found"}), 404
    return Response(p.read_bytes(), mimetype="image/png")


@app.route("/run/<run_id>/briefing/html")
def briefing_html(run_id):
    p = run_dir(run_id) / "briefing" / "briefing.html"
    if not p.exists():
        try:
            build_briefing(run_id)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return Response(p.read_text(encoding="utf-8"), mimetype="text/html")


@app.route("/run/<run_id>/briefing/pdf")
def briefing_pdf(run_id):
    p = run_dir(run_id) / "briefing" / "briefing.pdf"
    if not p.exists():
        try:
            build_briefing(run_id, with_pdf=True)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    if not p.exists():
        return jsonify({"error": "PDF unavailable: no working render engine "
                                 "(install weasyprint GTK libs, or run "
                                 "'playwright install chromium')"}), 501
    return Response(
        p.read_bytes(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_pdf_filename(run_id)}"'},
    )


def _pdf_filename(run_id: str) -> str:
    topic = ""
    try:
        run = read_json(run_id, "run.json") or {}
        topic = (run.get("topic") or "").strip()
        if not topic:
            qs = run.get("queries") or []
            topic = str((qs[0] or {}).get("q") or "") if qs else ""
    except Exception:
        pass
    slug = _re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return f"{slug or run_id}.pdf"


@app.route("/run/<run_id>/briefing/manifest")
def briefing_manifest(run_id):
    p = run_dir(run_id) / "briefing" / "briefing.json"
    if not p.exists():
        return jsonify({"error": "not generated"}), 404
    return Response(p.read_text(encoding="utf-8"), mimetype="application/json")


@app.route("/run/<run_id>/evidence")
def run_evidence(run_id):
    data = read_json(run_id, "evidence.json")
    if data is None:
        return jsonify({"error": "not generated"}), 404
    return jsonify(data)


@app.route("/fb/cookies/status")
def fb_cookies_status():
    return jsonify(fb_cookies.status())


@app.route("/fb/cookies/refresh/start", methods=["POST"])
def fb_cookies_refresh_start():
    try:
        job = fb_cookies.start_refresh()
    except FileNotFoundError as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500
    return jsonify({"ok": True, "job_id": job.id, "state": job.state})


@app.route("/fb/cookies/refresh/events")
def fb_cookies_refresh_events():
    job_id = request.args.get("job_id", "")
    if not fb_cookies.get(job_id):
        return jsonify({"error": "unknown job"}), 404

    @stream_with_context
    def gen():
        yield sse_format({"type": "open", "job_id": job_id})
        while True:
            for ev in fb_cookies.drain_events(job_id, timeout=5.0):
                yield sse_format(ev)
                if ev.get("type") in ("done", "cancelled"):
                    return
            yield ": keepalive\n\n"

    return Response(gen(), mimetype="text/event-stream")


@app.route("/fb/cookies/refresh/confirm", methods=["POST"])
def fb_cookies_refresh_confirm():
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(fb_cookies.confirm(data.get("job_id", "")))


@app.route("/fb/cookies/refresh/cancel", methods=["POST"])
def fb_cookies_refresh_cancel():
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(fb_cookies.cancel(data.get("job_id", "")))


@app.route("/events")
def events():
    run_id = request.args.get("run_id", "")
    q = BUS.subscribe(run_id)

    @stream_with_context
    def gen():
        # initial heartbeat so the EventSource connects cleanly
        yield sse_format({"type": "open", "run_id": run_id})
        while True:
            try:
                ev = q.get(timeout=30)
            except Exception:
                yield ": keepalive\n\n"
                continue
            yield sse_format(ev)
            if ev.get("type") == "_close":
                return

    return Response(gen(), mimetype="text/event-stream")


@app.route("/graph")
def graph():
    run_id = request.args.get("run_id", "")
    clusters = read_json(run_id, "clusters.json") or []
    nodes = [{
        "data": {
            "id": str(c["id"]),
            "label": c["label"],
            "size": len(c["members"]),
            "sentiment": c["sentiment"],
        }
    } for c in clusters]
    edges = []
    for i, a in enumerate(clusters):
        va = np.array(a["centroid"])
        for b in clusters[i + 1:]:
            vb = np.array(b["centroid"])
            sim = float(va @ vb)
            if sim > 0.5:
                edges.append({"data": {
                    "id": f"{a['id']}-{b['id']}",
                    "source": str(a["id"]),
                    "target": str(b["id"]),
                    "weight": sim,
                }})
    return jsonify({"nodes": nodes, "edges": edges})


@app.route("/run/<run_id>/cluster/<cid>")
def cluster_posts(run_id: str, cid: str):
    clusters = read_json(run_id, "clusters.json") or []
    posts = read_json(run_id, "posts.json") or []
    by_id = {str(p.get("id")): p for p in posts}
    match = next((c for c in clusters if str(c.get("id")) == str(cid)), None)
    if match is None:
        return jsonify({"error": "cluster not found"}), 404
    top = {str(i) for i in match.get("top_posts", [])}
    member_ids = [str(i) for i in match.get("members", [])]
    resolved = []
    for pid in member_ids:
        p = by_id.get(pid)
        if not p:
            continue
        resolved.append({
            "id": p.get("id"),
            "source": p.get("source", ""),
            "text": p.get("text", ""),
            "author": p.get("author"),
            "url": p.get("url"),
            "ts": p.get("ts", 0),
            "reactions": p.get("reactions", 0),
            "comments": p.get("comments", 0),
            "top": pid in top,
        })
    resolved.sort(key=lambda x: (not x["top"], -(x["reactions"] or 0)))
    return jsonify({
        "id": match.get("id"),
        "label": match.get("label", "Unlabeled"),
        "desc": match.get("desc", ""),
        "sentiment": match.get("sentiment", {}),
        "n": len(resolved),
        "posts": resolved,
    })


@app.route("/run/<run_id>/voices")
def voices(run_id: str):
    clusters = read_json(run_id, "clusters.json") or []
    posts = read_json(run_id, "posts.json") or []
    by_id = {str(p.get("id")): p for p in posts}

    agg = {"pos": 0.0, "neu": 0.0, "neg": 0.0}
    total = 0
    voices_pool = []
    themes = []
    for c in clusters:
        members = [str(i) for i in c.get("members", [])]
        n = len(members)
        if not n:
            continue
        total += n
        s = c.get("sentiment", {}) or {}
        for k in agg:
            agg[k] += float(s.get(k, 0)) * n
        bucket = max(("pos", "neu", "neg"), key=lambda k: float(s.get(k, 0)))
        label = c.get("label", "this topic")
        themes.append((n, label))
        top = [str(i) for i in c.get("top_posts", [])] or members
        for pid in top[:3]:
            p = by_id.get(pid)
            if not p or not (p.get("text") or "").strip():
                continue
            voices_pool.append({
                "text": p.get("text", ""),
                "source": p.get("source", ""),
                "url": p.get("url"),
                "author": p.get("author"),
                "reactions": p.get("reactions", 0) or 0,
                "ts": p.get("ts", 0),
                "bucket": bucket,
                "cluster": label,
            })
    if total:
        for k in agg:
            agg[k] = round(agg[k] / total, 3)

    voices_pool.sort(key=lambda v: -(v["reactions"] or 0))
    seen, carousel = set(), []
    for v in voices_pool:
        key = v["text"][:80]
        if key in seen:
            continue
        seen.add(key)
        carousel.append(v)

    notable, used_buckets = [], {}
    for v in carousel:
        b = v["bucket"]
        if used_buckets.get(b, 0) >= 2:
            continue
        used_buckets[b] = used_buckets.get(b, 0) + 1
        notable.append(v)
        if len(notable) >= 5:
            break

    themes.sort(key=lambda t: -t[0])
    return jsonify({
        "sentiment": agg,
        "voices": carousel[:12],
        "notable": notable,
        "themes": [t[1] for t in themes[:4]],
    })


@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json(force=True, silent=True) or {}
    run_id = data.get("run_id")
    q = (data.get("q") or "").strip()
    if not run_id or not q:
        return jsonify({"error": "run_id and q required"}), 400
    return jsonify(rag_ask(run_id, q))


# --- Chat workspace ---------------------------------------------------------

@app.route("/chat")
def chat_page():
    return render_template("chat.html")


@app.route("/chat/runs")
def chat_runs():
    out = []
    if ROOT.exists():
        for d in sorted(ROOT.iterdir(), key=lambda p: p.name, reverse=True):
            if not d.is_dir():
                continue
            run = read_json(d.name, "run.json")
            if not run:
                continue
            posts = read_json(d.name, "posts.json") or []
            out.append({"run_id": d.name, "topic": run.get("topic", "Untitled run"),
                        "n_posts": len(posts), "started_at": run.get("started_at")})
    return jsonify(out)


@app.route("/chat/suggestions")
def chat_suggestions():
    run_id = request.args.get("run_id", "")
    run = read_json(run_id, "run.json") or {}
    clusters = read_json(run_id, "clusters.json") or []
    topic = run.get("topic", "this topic")
    sugg = [f"What are people saying about {c['label']}?"
            for c in clusters[:3] if c.get("label")]
    for fallback in (f"Summarize the overall sentiment on {topic}.",
                     f"What are the main points of disagreement about {topic}?",
                     f"Who are the most influential voices on {topic}?"):
        if len(sugg) >= 4:
            break
        sugg.append(fallback)
    return jsonify({"topic": topic, "suggestions": sugg[:4]})


@app.route("/chat/threads", methods=["GET", "POST"])
def chat_threads():
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        run_id = data.get("run_id")
        if not run_id:
            return jsonify({"error": "run_id required"}), 400
        thread = chat_store.new_thread(run_id, title=(data.get("title") or "New chat"))
        chat_store.save_thread(thread)
        return jsonify(thread)
    run_id = request.args.get("run_id", "")
    return jsonify(chat_store.list_threads(run_id))


@app.route("/chat/thread/<thread_id>", methods=["GET", "DELETE"])
def chat_thread(thread_id):
    run_id = request.args.get("run_id", "")
    if request.method == "DELETE":
        ok = chat_store.delete_thread(run_id, thread_id)
        return jsonify({"deleted": ok})
    thread = chat_store.load_thread(run_id, thread_id)
    if thread is None:
        return jsonify({"error": "not found"}), 404
    if request.args.get("debug") == "1":
        return jsonify(thread)
    return jsonify({"id": thread["id"], "title": thread["title"],
                    "messages": thread["messages"], "summary": thread.get("summary", ""),
                    "archived_count": thread.get("archived_count", 0)})


@app.route("/chat/ask", methods=["POST"])
def chat_ask():
    data = request.get_json(force=True, silent=True) or {}
    run_id = data.get("run_id")
    thread_id = data.get("thread_id")
    q = (data.get("q") or "").strip()
    if not run_id or not q:
        return jsonify({"error": "run_id and q required"}), 400

    thread = chat_store.load_thread(run_id, thread_id) if thread_id else None
    if thread is None:
        thread = chat_store.new_thread(run_id, title=q[:48])
    if not thread["messages"]:
        thread["title"] = q[:48]
    preamble = chat_memory.build_preamble(thread)

    @stream_with_context
    def gen():
        yield sse_format({"type": "meta", "thread_id": thread["id"], "title": thread["title"]})
        final = None
        for ev in chat_engine.answer_stream(run_id, q, preamble=preamble):
            if ev.get("type") == "answer":
                final = ev
            yield sse_format(ev)
        chat_store.append_message(thread, "user", q)
        chat_store.append_message(
            thread, "assistant", (final or {}).get("answer", ""),
            citations_detail=(final or {}).get("citations_detail", []),
            confidence=(final or {}).get("confidence", 0.0))
        chat_memory.compact(thread)
        chat_store.save_thread(thread)
        yield sse_format({"type": "saved", "thread_id": thread["id"]})

    return Response(gen(), mimetype="text/event-stream")


@app.route("/run-info")
def run_info():
    run_id = request.args.get("run_id", "")
    run = read_json(run_id, "run.json")
    clusters = read_json(run_id, "clusters.json")
    posts = read_json(run_id, "posts.json")
    posts_by_id = {p["id"]: p for p in (posts or [])}
    return jsonify({"run": run, "clusters": clusters, "posts": posts_by_id,
                    "max_iter": replay_max_iter(run)})


@app.route("/replay")
def replay():
    run_id = request.args.get("run_id", "")
    try:
        iter_n = int(request.args.get("iter", "1"))
    except (TypeError, ValueError):
        iter_n = 1
    iter_n = max(1, iter_n)
    return jsonify(replay_frame(run_id, iter_n))


# --- Legacy v1 endpoints (kept for backward compat) -------------------------


def _count_files(directory: str, extension: str | None = None,
                 exclude: str | None = None) -> int:
    if not os.path.exists(directory):
        return 0
    n = 0
    for f in os.listdir(directory):
        if extension and not f.lower().endswith(extension):
            continue
        if exclude and exclude.lower() in f.lower():
            continue
        n += 1
    return n


@app.route("/status")
def get_status():
    try:
        ss = sum(_count_files("screenshots", ext) for ext in (".png", ".jpg", ".jpeg"))
        jsons = _count_files("data", ".json", "facebook")
        summary = "File not found"
        sp = "data/facebook_posts_summary.txt"
        if os.path.exists(sp):
            with open(sp) as f:
                summary = f.read().strip()
        return jsonify({"screenshots": ss, "json_files": jsons, "summary": summary})
    except Exception as e:
        return jsonify({"screenshots": "Error", "json_files": "Error",
                        "summary": f"Error: {e}"}), 500


@app.route("/run-command", methods=["POST"])
def run_command():
    data = request.get_json(force=True, silent=True) or {}
    cmd = data.get("command")
    if cmd not in ("scrape", "process", "summarize"):
        return jsonify({"success": False, "error": "Invalid command"}), 400

    def bg():
        subprocess.run(["python", "main.py", cmd], capture_output=True, timeout=3600)

    threading.Thread(target=bg, daemon=True).start()
    return jsonify({"success": True, "message": f"{cmd} started"})


if __name__ == "__main__":
    import os as _os
    # debug=True keeps the Werkzeug error pages + verbose request log so
    # you can see what the server is doing. use_reloader stays OFF
    # because the reloader restarts the process on code edits and that
    # kills the long-lived /events SSE stream mid-run. Opt in to the
    # reloader with PT_RELOAD=1 when you actively want hot-reload (will
    # drop in-flight runs).
    reload_on = _os.environ.get("PT_RELOAD", "0") == "1"
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True
    print(f"PulseTrace v2 -> http://localhost:5000 "
          f"(debug=on, reload={int(reload_on)}; templates auto-reload)")
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True,
            use_reloader=reload_on)
