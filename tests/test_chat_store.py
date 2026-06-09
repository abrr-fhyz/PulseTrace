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


class _FakePg:
    """Records calls; reconstructs DB reads from what was written."""
    enabled = True

    def __init__(self):
        self.convs: dict[str, dict] = {}
        self.msgs: dict[str, list[dict]] = {}

    def upsert_conversation(self, conv):
        self.convs[conv["id"]] = dict(conv); return True

    def insert_message(self, cid, role, content, metadata=None):
        self.msgs.setdefault(cid, []).append(
            {"role": role, "content": content, "metadata": metadata or {}})
        return True

    def get_conversation(self, cid):
        return self.convs.get(cid)

    def get_messages(self, cid):
        return list(self.msgs.get(cid, []))

    def list_conversations(self, topic_id):
        return [{"id": c["id"], "title": c["title"], "created": 0, "updated": 0,
                 "message_count": len(self.msgs.get(c["id"], []))}
                for c in self.convs.values() if c["topic_id"] == topic_id]

    def delete_conversation(self, cid):
        self.convs.pop(cid, None); self.msgs.pop(cid, None); return True


def test_dual_write_and_db_first_read(tmp_path, monkeypatch):
    from lib import chat_store, store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(store, "read_json",
                        lambda rid, name: {"topic": "Elden Ring", "topic_id": "elden"})
    fake = _FakePg()
    monkeypatch.setattr(chat_store, "_pg", lambda: fake)

    thread = chat_store.new_thread("run1", title="hi?")
    assert thread["topic_id"] == "elden"
    chat_store.append_message(thread, "user", "hi?")
    chat_store.append_message(thread, "assistant", "hello", confidence=0.8)
    chat_store.save_thread(thread)

    assert fake.convs[thread["id"]]["title"] == "hi?"
    assert [m["role"] for m in fake.msgs[thread["id"]]] == ["user", "assistant"]

    loaded = chat_store.load_thread("run1", thread["id"])
    assert [m["content"] for m in loaded["messages"]] == ["hi?", "hello"]

    rows = chat_store.list_threads("run1")
    assert rows[0]["id"] == thread["id"]


def test_working_set_skips_archived(tmp_path, monkeypatch):
    from lib import chat_store, store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(store, "read_json", lambda rid, name: {"topic_id": "t"})
    fake = _FakePg()
    monkeypatch.setattr(chat_store, "_pg", lambda: fake)
    fake.convs["c1"] = {"id": "c1", "topic_id": "t", "run_id": "run1",
                        "title": "x", "summary": "S", "archived_count": 1}
    for i in range(3):
        fake.msgs.setdefault("c1", [])
        fake.msgs["c1"].append({"role": "user", "content": f"u{i}", "metadata": {}})
        fake.msgs["c1"].append({"role": "assistant", "content": f"a{i}", "metadata": {}})

    ws = chat_store.load_thread("run1", "c1")
    assert [m["content"] for m in ws["messages"]] == ["u1", "a1", "u2", "a2"]
    assert ws["summary"] == "S"


def test_full_history_includes_archived(tmp_path, monkeypatch):
    from lib import chat_store, store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(store, "read_json", lambda rid, name: {"topic_id": "t"})
    fake = _FakePg()
    monkeypatch.setattr(chat_store, "_pg", lambda: fake)
    fake.convs["c1"] = {"id": "c1", "topic_id": "t", "run_id": "run1",
                        "title": "x", "summary": "S", "archived_count": 1}
    for i in range(3):
        fake.msgs.setdefault("c1", [])
        fake.msgs["c1"].append({"role": "user", "content": f"u{i}", "metadata": {}})
        fake.msgs["c1"].append({"role": "assistant", "content": f"a{i}",
                                 "metadata": {"confidence": 0.7}})
    full = chat_store.load_thread_full("run1", "c1")
    assert [m["content"] for m in full["messages"]] == \
        ["u0", "a0", "u1", "a1", "u2", "a2"]
    assert full["messages"][1]["confidence"] == 0.7


def test_fallback_to_file_when_pg_disabled(tmp_path, monkeypatch):
    from lib import chat_store, store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(store, "read_json", lambda rid, name: {"topic_id": "t"})
    monkeypatch.setattr(chat_store, "_pg", lambda: None)

    thread = chat_store.new_thread("run1", title="q")
    chat_store.append_message(thread, "user", "q")
    chat_store.save_thread(thread)
    loaded = chat_store.load_thread("run1", thread["id"])
    assert loaded is not None
    assert loaded["messages"][0]["content"] == "q"
