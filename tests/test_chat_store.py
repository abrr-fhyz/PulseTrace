from __future__ import annotations

import pytest


@pytest.fixture()
def cs(tmp_path, monkeypatch):
    import lib.store as store
    monkeypatch.setattr(store, "ROOT", tmp_path / "runs")
    import lib.chat_store as chat_store
    return chat_store


def test_new_thread_has_defaults(cs):
    t = cs.new_thread("run1", title="Battery talk")
    assert t["run_id"] == "run1"
    assert t["title"] == "Battery talk"
    assert t["summary"] == ""
    assert t["archived_count"] == 0
    assert t["messages"] == []
    assert t["id"]


def test_save_and_load_roundtrip(cs):
    t = cs.new_thread("run1")
    cs.append_message(t, "user", "hello")
    cs.append_message(t, "assistant", "hi", citations_detail=[{"id": "x"}], confidence=0.9)
    cs.save_thread(t)

    got = cs.load_thread("run1", t["id"])
    assert len(got["messages"]) == 2
    assert got["messages"][0]["role"] == "user"
    assert got["messages"][1]["confidence"] == 0.9
    assert got["messages"][1]["citations_detail"] == [{"id": "x"}]


def test_load_missing_returns_none(cs):
    assert cs.load_thread("run1", "nope") is None


def test_list_threads_sorted_newest_first(cs):
    a = cs.new_thread("run1", title="a")
    cs.save_thread(a)
    b = cs.new_thread("run1", title="b")
    b["updated"] = a["updated"] + 100
    cs.save_thread(b)

    rows = cs.list_threads("run1")
    assert [r["id"] for r in rows] == [b["id"], a["id"]]
    assert "messages" not in rows[0]  # list view is a summary, not full payload


def test_list_threads_empty_run(cs):
    assert cs.list_threads("ghost") == []


def test_delete_thread(cs):
    t = cs.new_thread("run1")
    cs.save_thread(t)
    assert cs.load_thread("run1", t["id"]) is not None
    assert cs.delete_thread("run1", t["id"]) is True
    assert cs.load_thread("run1", t["id"]) is None
    assert cs.delete_thread("run1", t["id"]) is False
