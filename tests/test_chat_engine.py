from __future__ import annotations

import lib.chat_engine as ce


def _setup(monkeypatch, judge_conf=0.9):
    monkeypatch.setattr(ce, "_ensure_index", lambda rid: True)
    monkeypatch.setattr(ce, "_load_posts_dict", lambda rid: {"p1": {"text": "battery great"}})
    monkeypatch.setattr(ce, "hybrid_search", lambda rid, q, k: ["p1"])
    monkeypatch.setattr(ce, "_citation_detail", lambda rid, c, posts: {"id": c})

    def fake_chat(system, user, **k):
        if system is ce.ASK_SYS:
            return {"answer": "Battery is praised [p1].", "citations": ["p1"]}
        if system is ce.JUDGE_SYS:
            return {"confidence": judge_conf, "supported": True, "gap": ""}
        return {"query": "battery"}
    monkeypatch.setattr(ce, "chat_json", fake_chat)


def test_stream_emits_stages_then_answer_then_done(monkeypatch):
    _setup(monkeypatch)
    events = list(ce.answer_stream("run1", "how is battery"))

    stages = [e["stage"] for e in events if "stage" in e]
    assert stages[:4] == ["retrieving", "retrieved", "drafting", "verifying"]
    assert events[-1] == {"type": "done"}

    answer = [e for e in events if e.get("type") == "answer"][0]
    assert "Battery" in answer["answer"]
    assert answer["confidence"] == 0.9
    assert answer["citations_detail"] == [{"id": "p1"}]


def test_low_confidence_triggers_refine_loop(monkeypatch):
    _setup(monkeypatch, judge_conf=0.1)
    events = list(ce.answer_stream("run1", "how is battery"))
    stages = [e["stage"] for e in events if "stage" in e]
    assert "refining" in stages                       # reflected at least once
    answer = [e for e in events if e.get("type") == "answer"][0]
    assert answer["iterations"] >= 2


def test_no_data_short_circuits(monkeypatch):
    monkeypatch.setattr(ce, "_ensure_index", lambda rid: False)
    events = list(ce.answer_stream("empty", "anything"))
    assert events[0]["answer"] == "No data for this run."
    assert events[-1] == {"type": "done"}


def test_preamble_flows_into_draft(monkeypatch):
    seen = {}
    monkeypatch.setattr(ce, "_ensure_index", lambda rid: True)
    monkeypatch.setattr(ce, "_load_posts_dict", lambda rid: {"p1": {"text": "x"}})
    monkeypatch.setattr(ce, "hybrid_search", lambda rid, q, k: ["p1"])
    monkeypatch.setattr(ce, "_citation_detail", lambda rid, c, posts: {"id": c})

    def fake_chat(system, user, **k):
        if system is ce.ASK_SYS:
            seen["draft_user"] = user
            return {"answer": "ok", "citations": []}
        return {"confidence": 0.9, "gap": ""}
    monkeypatch.setattr(ce, "chat_json", fake_chat)

    list(ce.answer_stream("run1", "q", preamble="PRIOR CONTEXT HERE"))
    assert "PRIOR CONTEXT HERE" in seen["draft_user"]
