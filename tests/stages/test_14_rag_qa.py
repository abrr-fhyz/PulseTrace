"""Stage 14: RAG Q&A over a real run.

Backs README "Step 7 — RAG Q&A — search corpus with FAISS, cited answers".
Questions are configurable via PT_RAG_QUESTIONS (pipe-separated).
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path

import pytest

from .conftest import (TOPIC, RAG_QUESTIONS, RESULTS_DIR,
                       pick_chat_provider, pick_embed_provider,
                       write_stage_artifact, REPO_ROOT)


def _run_id_with_data(monkeypatch, chat: str, embed: str):
    from lib import agent, store
    monkeypatch.setattr(agent, "MAX_ITERS", 2)
    monkeypatch.setattr(agent, "MAX_POSTS", 30)
    rid = agent.run_agent(TOPIC, ["hn"])
    posts = store.read_json(rid, "posts.json") or []
    if len(posts) < 4:
        pytest.skip(f"only {len(posts)} posts collected for {TOPIC!r} — "
                    f"too few for meaningful RAG")
    return rid


def test_rag_index_builds_and_answers(monkeypatch):
    chat = pick_chat_provider()
    embed = pick_embed_provider()
    if not chat or not embed:
        pytest.skip("provider(s) unavailable")
    monkeypatch.setenv("PULSETRACE_BACKEND", chat)
    monkeypatch.setenv("PULSETRACE_EMBED_BACKEND", embed)

    rid = _run_id_with_data(monkeypatch, chat, embed)

    from lib.rag import ask, build_index
    from lib.store import run_dir
    build_index(rid)
    idx = run_dir(rid) / "index.faiss"
    assert idx.exists() and idx.stat().st_size > 0, "FAISS index not written"

    answers = []
    for q in RAG_QUESTIONS:
        out = ask(rid, q, k=5)
        assert isinstance(out, dict)
        assert "answer" in out and isinstance(out["answer"], str)
        assert "retrieved" in out and isinstance(out["retrieved"], list)
        answers.append({
            "question": q,
            "answer": out["answer"],
            "citations": out.get("citations", []),
            "n_retrieved": len(out["retrieved"]),
        })

    # Persist Q&A alongside the main result JSON so the webapp's Ask-box
    # state is reproducible from disk.
    RESULTS_DIR.mkdir(exist_ok=True)
    payload = {
        "topic": TOPIC, "run_id": rid,
        "chat": chat, "embed": embed,
        "qa": answers,
        "generated_at": int(time.time()),
    }
    from tests.stages.test_08_full_agent_to_root_json import _slug
    qa_path = RESULTS_DIR / f"{_slug(TOPIC)}_rag.json"
    qa_path.write_text(json.dumps(payload, indent=2, default=str))
    write_stage_artifact("stage14_rag.json", {
        "run_id": rid, "n_questions": len(answers),
        "out_path": str(qa_path.relative_to(REPO_ROOT)),
    })
    print(f"\n[stage14] wrote {qa_path.relative_to(REPO_ROOT)}")
    print(f"[stage14] {len(answers)} answers (avg cites={sum(len(a['citations']) for a in answers)/max(len(answers),1):.1f})")


def test_rag_handles_missing_index_gracefully():
    """ask() on a non-existent run must not raise."""
    from lib.rag import ask
    out = ask("does-not-exist-run-id", "anything?")
    assert isinstance(out, dict)
    assert "answer" in out
