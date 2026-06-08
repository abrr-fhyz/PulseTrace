from __future__ import annotations

import json
from unittest.mock import patch

import numpy as np

from lib import rag, store


def _patch(monkeypatch, chat_side, hits=("p1",)):
    monkeypatch.setattr(rag, "hybrid_search", lambda run_id, q, k: list(hits))
    monkeypatch.setattr(
        rag, "_load_posts_dict", lambda run_id: {"p1": {"id": "p1", "text": "ctx"}}
    )
    monkeypatch.setattr(rag, "_ensure_index", lambda run_id: True)
    calls = {"chat": []}

    def fake_chat(system, user, stage=None):
        calls["chat"].append(stage)
        return chat_side.pop(0)

    monkeypatch.setattr(rag, "chat_json", fake_chat)
    return calls


def test_ask_high_confidence_single_iteration(monkeypatch):
    side = [
        {"answer": "A", "citations": ["p1"]},   # ASK
        {"confidence": 0.9, "supported": True, "gap": ""},  # JUDGE
    ]
    calls = _patch(monkeypatch, side)
    out = rag.ask("run1", "q?")
    assert out["answer"] == "A"
    assert out["iterations"] == 1
    assert out["confidence"] == 0.9
    assert "rag_refine" not in calls["chat"]


def test_ask_low_then_high_triggers_refine_and_reretrieval(monkeypatch):
    side = [
        {"answer": "A1", "citations": []},               # ASK iter1
        {"confidence": 0.3, "supported": False, "gap": "missing X"},  # JUDGE iter1
        {"query": "q refined"},                          # REFINE
        {"answer": "A2", "citations": ["p1"]},           # ASK iter2
        {"confidence": 0.9, "supported": True, "gap": ""},  # JUDGE iter2
    ]
    calls = _patch(monkeypatch, side)
    out = rag.ask("run1", "q?")
    assert out["answer"] == "A2"
    assert out["iterations"] == 2
    assert calls["chat"].count("rag") == 2  # two answer passes


def test_ask_caps_at_max_iters(monkeypatch):
    side = [
        {"answer": "A1", "citations": []},
        {"confidence": 0.2, "supported": False, "gap": "g"},
        {"query": "q2"},
        {"answer": "A2", "citations": []},
        {"confidence": 0.25, "supported": False, "gap": "g"},
    ]
    _patch(monkeypatch, side)
    out = rag.ask("run1", "q?")
    assert out["iterations"] == 2
    assert out["answer"] == "A2"  # best (higher conf) of the two low answers


def test_ask_judge_failure_returns_answer(monkeypatch):
    side = [{"answer": "A", "citations": ["p1"]}]

    def fake_chat(system, user, stage=None):
        if not side:
            raise RuntimeError("judge boom")
        return side.pop(0)

    monkeypatch.setattr(rag, "hybrid_search", lambda run_id, q, k: ["p1"])
    monkeypatch.setattr(
        rag, "_load_posts_dict", lambda run_id: {"p1": {"id": "p1", "text": "c"}}
    )
    monkeypatch.setattr(rag, "_ensure_index", lambda run_id: True)
    monkeypatch.setattr(rag, "chat_json", fake_chat)
    out = rag.ask("run1", "q?")
    assert out["answer"] == "A"
    assert out["iterations"] == 1
    assert out["confidence"] == 1.0


def test_build_and_ask(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    rid = "test-run"
    d = store.run_dir(rid)
    posts = [
        {"id": "a", "text": "cats are great"},
        {"id": "b", "text": "dogs love walks"},
    ]
    (d / "posts.json").write_text(json.dumps(posts))

    fake_emb = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    with patch("lib.rag.embed_texts", return_value=fake_emb):
        rag.build_index(rid)

    qvec = np.array([[1.0, 0.0]], dtype=np.float32)
    with patch("lib.rag.embed_texts", return_value=qvec), \
         patch("lib.retrieve.embed_texts", return_value=qvec), \
         patch("lib.rag.chat_json", return_value={"answer": "cats", "citations": ["a"]}):
        res = rag.ask(rid, "tell me about cats", k=1)
    assert res["answer"] == "cats"
    assert "a" in res["retrieved"]


def test_ask_no_data(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    res = rag.ask("missing", "?")
    assert res["answer"].startswith("No data")
