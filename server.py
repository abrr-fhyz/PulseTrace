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
from lib.store import read_json
from lib.rag import ask as rag_ask


app = Flask(__name__)
CORS(app)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/run", methods=["POST"])
def start_run():
    data = request.get_json(force=True, silent=True) or {}
    topic = (data.get("topic") or "").strip()
    sources = data.get("sources") or ["reddit", "hn"]
    if not topic:
        return jsonify({"error": "topic required"}), 400

    holder: dict = {}

    def go():
        try:
            holder["run_id"] = run_agent(topic, sources)
        except Exception as e:
            holder["error"] = str(e)

    threading.Thread(target=go, daemon=True).start()

    # Agent publishes "started" with run_id immediately; we wait briefly to capture it.
    for _ in range(40):
        if holder.get("run_id") or holder.get("error"):
            break
        time.sleep(0.05)
    if holder.get("error") and not holder.get("run_id"):
        return jsonify({"error": holder["error"]}), 500
    return jsonify({"run_id": holder.get("run_id")})


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
