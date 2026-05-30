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

from lib.agent import run_agent
from lib.events import BUS, sse_format
from lib.store import read_json, new_run_id
from lib.rag import ask as rag_ask
from lib import backend, fb_cookies


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

    run_id = new_run_id()

    def go():
        prior = _byok_apply(byok)
        try:
            run_agent(topic, sources, run_id=run_id)
        except Exception as e:
            BUS.publish(run_id, {"type": "error", "err": str(e)})
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


@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json(force=True, silent=True) or {}
    run_id = data.get("run_id")
    q = (data.get("q") or "").strip()
    if not run_id or not q:
        return jsonify({"error": "run_id and q required"}), 400
    return jsonify(rag_ask(run_id, q))


@app.route("/run-info")
def run_info():
    run_id = request.args.get("run_id", "")
    run = read_json(run_id, "run.json")
    clusters = read_json(run_id, "clusters.json")
    posts = read_json(run_id, "posts.json")
    posts_by_id = {p["id"]: p for p in (posts or [])}
    return jsonify({"run": run, "clusters": clusters, "posts": posts_by_id})


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
    print("PulseTrace v2 -> http://localhost:5000")
    app.run(debug=False, host="0.0.0.0", port=5000, threaded=True)
