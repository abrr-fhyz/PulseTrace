"""Stage 15: live webapp HTTP endpoints.

Backs README "5. Run Server -> open localhost:5000" + the Flask routes in
server.py (/run, /events, /run-info, /graph, /ask). Skipped if server isn't
running at WEBAPP_URL. Saves the live /run-info + /graph payloads next to
the rest of the results so they can be diffed against the in-process JSON.
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path

import pytest
import requests

from .conftest import TOPIC, RESULTS_DIR, REPO_ROOT, RAG_QUESTIONS


WEBAPP_URL = os.environ.get("PT_WEBAPP_URL", "http://127.0.0.1:5000").rstrip("/")


def _server_up() -> bool:
    try:
        return requests.get(WEBAPP_URL + "/", timeout=2).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _server_up(),
                                reason=f"webapp not reachable at {WEBAPP_URL}")


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "topic"


def _wait_for_run_complete(run_id: str, timeout: float = 180.0) -> bool:
    """Poll /run-info until run.json reports a stop_reason or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{WEBAPP_URL}/run-info",
                             params={"run_id": run_id}, timeout=10)
            if r.status_code == 200:
                info = r.json() or {}
                if (info.get("run") or {}).get("stop_reason"):
                    return True
        except Exception:
            pass
        time.sleep(2.0)
    return False


def test_webapp_index_loads():
    r = requests.get(WEBAPP_URL + "/", timeout=5)
    assert r.status_code == 200
    assert "PulseTrace" in r.text


def test_webapp_full_topic_flow():
    """POST /run -> wait -> GET /run-info -> GET /graph -> POST /ask."""
    payload = {"topic": TOPIC, "sources": ["facebook"]}
    r = requests.post(f"{WEBAPP_URL}/run", json=payload, timeout=15)
    assert r.status_code == 200, f"/run returned {r.status_code}: {r.text[:200]}"
    body = r.json()
    run_id = body.get("run_id")
    assert run_id, f"no run_id in /run response: {body}"

    completed = _wait_for_run_complete(run_id, timeout=240)
    assert completed, f"run {run_id} did not complete in time"

    info = requests.get(f"{WEBAPP_URL}/run-info",
                        params={"run_id": run_id}, timeout=10).json()
    graph = requests.get(f"{WEBAPP_URL}/graph",
                         params={"run_id": run_id}, timeout=10).json()

    qa_answers = []
    if (info.get("posts") or info.get("run", {}).get("metrics", {}).get("posts", 0)):
        for q in RAG_QUESTIONS[:2]:
            r = requests.post(f"{WEBAPP_URL}/ask",
                              json={"run_id": run_id, "q": q}, timeout=120)
            if r.status_code == 200:
                qa_answers.append({"q": q, **r.json()})

    out = RESULTS_DIR / f"{_slug(TOPIC)}_webapp.json"
    RESULTS_DIR.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "topic": TOPIC, "run_id": run_id,
        "webapp_url": WEBAPP_URL,
        "run_info": info,
        "graph": graph,
        "qa": qa_answers,
        "fetched_at": int(time.time()),
    }, indent=2, default=str))
    print(f"\n[stage15] wrote {out.relative_to(REPO_ROOT)} "
          f"({out.stat().st_size} bytes)")

    assert isinstance(graph, dict)
    assert "nodes" in graph and "edges" in graph
    # If posts were collected, /run-info should reflect that.
    run_meta = (info.get("run") or {}).get("metrics") or {}
    posts_n = run_meta.get("posts", info.get("posts") or 0)
    if isinstance(posts_n, list):
        posts_n = len(posts_n)
    assert isinstance(posts_n, int)
