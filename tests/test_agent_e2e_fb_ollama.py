"""End-to-end test: Facebook connector + Ollama backend + agent loop.

Requires ALL of:
  FB_INTEGRATION=1
  info/cookies.json populated
  PULSETRACE_BACKEND=ollama
  Ollama serving with chat + embed models pulled
  Playwright Chromium installed

Run with:
  FB_INTEGRATION=1 PULSETRACE_BACKEND=ollama \\
    .venv/bin/python -m pytest tests/test_agent_e2e_fb_ollama.py -v -m slow

This test exercises the full pipeline against real FB + real local LLM.
Expect it to take several minutes on a 16 GB box.
"""
from __future__ import annotations
import os
from pathlib import Path
import pytest
import requests

pytestmark = pytest.mark.slow


def _all_ready() -> tuple[bool, str]:
    if os.environ.get("FB_INTEGRATION", "") != "1":
        return False, "FB_INTEGRATION!=1"
    if os.environ.get("PULSETRACE_BACKEND", "").lower() != "ollama":
        return False, "PULSETRACE_BACKEND!=ollama"
    if not (Path("info/cookies.json").exists()
            and Path("info/cookies.json").stat().st_size > 50):
        return False, "info/cookies.json missing"
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        if requests.get(f"{host}/api/tags", timeout=5).status_code != 200:
            return False, "Ollama unreachable"
    except Exception:
        return False, "Ollama unreachable"
    return True, ""


_READY, _REASON = _all_ready()
_GATE = pytest.mark.skipif(not _READY, reason=_REASON)


@_GATE
def test_agent_full_loop_fb_only(monkeypatch, tmp_path):
    from lib import agent, store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(agent, "MAX_POSTS", 20)
    monkeypatch.setattr(agent, "MAX_ITERS", 1)

    run_id = agent.run_agent("technology", ["facebook"])
    assert run_id

    run = store.read_json(run_id, "run.json")
    assert run is not None
    assert run["topic"] == "technology"
    assert run["sources"] == ["facebook"]
    assert run["metrics"]["posts"] >= 0

    posts = store.read_json(run_id, "posts.json")
    clusters = store.read_json(run_id, "clusters.json")
    if (posts or []) and len(posts) >= 6:
        assert clusters and len(clusters) >= 1
        for c in clusters:
            assert "label" in c and isinstance(c["label"], str)
            assert "sentiment" in c
            s = c["sentiment"]
            assert all(0.0 <= s[k] <= 1.0 for k in ("pos", "neu", "neg"))
            assert abs(s["pos"] + s["neu"] + s["neg"] - 1.0) < 0.05


@_GATE
def test_rag_over_fb_run(monkeypatch, tmp_path):
    from lib import agent, store, rag
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(agent, "MAX_POSTS", 15)
    monkeypatch.setattr(agent, "MAX_ITERS", 1)

    run_id = agent.run_agent("technology", ["facebook"])
    posts = store.read_json(run_id, "posts.json") or []
    if len(posts) < 4:
        pytest.skip(f"not enough posts ({len(posts)}) for meaningful RAG")

    answer = rag.ask(run_id, "summarize the main themes")
    assert isinstance(answer, dict)
    assert "answer" in answer and isinstance(answer["answer"], str)
    assert len(answer["answer"]) > 0
    assert "retrieved" in answer
