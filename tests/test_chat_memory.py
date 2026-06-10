from __future__ import annotations

import pytest

import lib.chat_memory as cm


def _thread(n_pairs: int, summary: str = "") -> dict:
    msgs = []
    for i in range(n_pairs):
        msgs.append({"role": "user", "content": f"q{i}"})
        msgs.append({"role": "assistant", "content": f"a{i}"})
    return {"summary": summary, "archived_count": 0, "messages": msgs}


def test_compact_noop_under_threshold(monkeypatch):
    called = []
    monkeypatch.setattr(cm, "chat_json", lambda *a, **k: called.append(1) or {"summary": "x"})
    t = _thread(cm.RECENT_TURNS)  # exactly at limit
    cm.compact(t)
    assert called == []                      # no LLM call
    assert len(t["messages"]) == cm.RECENT_TURNS * 2
    assert t["archived_count"] == 0


def test_compact_folds_overflow_into_summary(monkeypatch):
    monkeypatch.setattr(cm, "chat_json", lambda *a, **k: {"summary": "rolled up"})
    t = _thread(cm.RECENT_TURNS + 3)         # 3 turns over
    cm.compact(t)
    assert t["summary"] == "rolled up"
    assert t["archived_count"] == 3
    assert len(t["messages"]) == cm.RECENT_TURNS * 2
    # the oldest pairs were dropped; newest survive verbatim
    assert t["messages"][0]["content"] == "q3"
    assert t["messages"][-1]["content"] == f"a{cm.RECENT_TURNS + 2}"


def test_compact_passes_existing_summary_to_llm(monkeypatch):
    seen = {}
    def fake(system, user, **k):
        seen["user"] = user
        return {"summary": "merged"}
    monkeypatch.setattr(cm, "chat_json", fake)
    t = _thread(cm.RECENT_TURNS + 1, summary="prior summary")
    cm.compact(t)
    assert "prior summary" in seen["user"]    # prior summary carried forward
    assert t["summary"] == "merged"


def test_compact_ignores_trailing_unanswered_user(monkeypatch):
    monkeypatch.setattr(cm, "chat_json", lambda *a, **k: {"summary": "s"})
    t = _thread(cm.RECENT_TURNS)
    t["messages"].append({"role": "user", "content": "dangling"})  # no assistant yet
    cm.compact(t)
    # still at/under threshold by turns → no archiving, dangling preserved
    assert t["archived_count"] == 0
    assert t["messages"][-1]["content"] == "dangling"


def test_build_preamble_empty():
    assert cm.build_preamble({"summary": "", "messages": []}) == ""


def test_build_preamble_includes_summary_and_recent():
    t = {"summary": "older stuff", "messages": [
        {"role": "user", "content": "what about price"},
        {"role": "assistant", "content": "high"},
    ]}
    p = cm.build_preamble(t)
    assert "older stuff" in p
    assert "what about price" in p
    assert "high" in p


def test_build_preamble_recent_only_no_summary():
    t = {"summary": "", "messages": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]}
    p = cm.build_preamble(t)
    assert "hi" in p and "hello" in p
