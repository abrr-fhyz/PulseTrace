# Persistent Conversational Chat (Supabase) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist all chat history in Supabase as the durable source of truth (dual-write + file fallback), preserve the rolling-summary memory exactly, and tighten chat UI/navigation.

**Architecture:** Mirror `lib/store.py`'s additive pattern. `lib/chat_store.py` dual-writes to file (memory working-set + cold-demo fallback) and Supabase (`conversations` + append-only `messages`). `lib/chat_memory.py` is untouched. DB reads are source-of-truth when enabled; the answering path reconstructs the compacted working-set from DB so memory logic is unchanged.

**Tech Stack:** Python 3.12, psycopg2 + pgvector (Supabase), Flask + SSE, vanilla JS (Jinja templates, no build step), pytest.

**Spec:** `.claude/specs/2026-06-10-persistent-chat-supabase-design.md`

---

## File Structure

- `db/schema.sql` — **modify**: add `conversations` + `messages` tables (idempotent).
- `db/supabase_client.py` — **modify**: add 6 conversation/message methods.
- `lib/chat_store.py` — **modify**: dual-write + DB-first reads + working-set reconstruction.
- `server.py` — **modify**: `/chat/thread/<id>` GET uses full-history loader.
- `templates/chat.html` — **modify**: back→`#/app`; persist+rehydrate `thread_id`.
- `templates/index.html` — **modify**: remove inline ask panel → CTA card; prominent nav chat icon; same-tab open; drop dead `ask()`.
- `tests/test_chat_store.py` — **modify**: dual-write + fallback tests (fake pg stub).
- `tests/test_supabase_chat.py` — **create**: live conversation/message tests (gated on `DATABASE_URL`).

---

## Task 1: Schema — conversations + messages tables

**Files:**
- Modify: `db/schema.sql` (append at end, after the `run_artifacts` block)

- [ ] **Step 1: Append the two tables to `db/schema.sql`**

```sql
-- ---------------------------------------------------------------- conversations
-- Persistent chat history. `topic_id` is the owner/group key (project has no
-- auth); `run_id` is the corpus a conversation's RAG retrieves against.
CREATE TABLE IF NOT EXISTS conversations (
    id             text PRIMARY KEY,
    topic_id       text NOT NULL,
    run_id         text NOT NULL,
    title          text NOT NULL DEFAULT 'New chat',
    summary        text NOT NULL DEFAULT '',
    archived_count integer NOT NULL DEFAULT 0,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_conversations_topic
    ON conversations (topic_id, updated_at DESC);
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------- messages
-- Append-only full history (never deleted by memory compaction). The file
-- working-set holds only the compacted recent turns; the DB keeps everything.
CREATE TABLE IF NOT EXISTS messages (
    id              bigserial PRIMARY KEY,
    conversation_id text NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            text NOT NULL,
    content         text NOT NULL DEFAULT '',
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_messages_convo
    ON messages (conversation_id, created_at);
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
```

- [ ] **Step 2: Verify SQL is syntactically valid (no DB needed)**

Run: `python -c "import re,sys; sql=open('db/schema.sql').read(); assert sql.count('(') == sql.count(')'), 'paren mismatch'; assert 'conversations' in sql and 'messages' in sql; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add db/schema.sql
git commit -m "feat(db): conversations + messages schema for persistent chat"
```

---

## Task 2: SupabaseClient conversation/message methods

**Files:**
- Modify: `db/supabase_client.py` (add methods inside `class SupabaseClient`, after `get_artifact`, before `health`)
- Create: `tests/test_supabase_chat.py`

- [ ] **Step 1: Write the failing live test**

```python
# tests/test_supabase_chat.py
"""Live conversation/message persistence — gated on DATABASE_URL.

Skipped in the default (mocked) suite; runs against a real Supabase/Postgres
when DATABASE_URL is set and the schema has been applied.
"""
from __future__ import annotations

import os
import uuid

import pytest

from db.supabase_client import SupabaseClient

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")),
    reason="no DATABASE_URL — live DB test",
)


@pytest.fixture()
def pg():
    client = SupabaseClient()
    assert client.enabled, "expected an enabled client with DATABASE_URL set"
    client.apply_schema("db/schema.sql")
    yield client
    client.close()


def test_conversation_roundtrip(pg):
    cid = "test_" + uuid.uuid4().hex[:8]
    conv = {"id": cid, "topic_id": "t-pytest", "run_id": "r-pytest",
            "title": "First Q", "summary": "", "archived_count": 0}
    assert pg.upsert_conversation(conv) is True

    assert pg.insert_message(cid, "user", "hello", {"confidence": None}) is True
    assert pg.insert_message(cid, "assistant", "hi there", {"confidence": 0.9}) is True

    msgs = pg.get_messages(cid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"] == "hi there"
    assert msgs[1]["metadata"]["confidence"] == 0.9

    got = pg.get_conversation(cid)
    assert got["title"] == "First Q"

    rows = pg.list_conversations("t-pytest")
    assert any(r["id"] == cid and r["message_count"] == 2 for r in rows)

    assert pg.delete_conversation(cid) is True
    assert pg.get_conversation(cid) is None
    assert pg.get_messages(cid) == []  # FK cascade
```

- [ ] **Step 2: Run it — verify it fails (methods missing) or skips (no DB)**

Run: `.venv/bin/python -m pytest tests/test_supabase_chat.py -v`
Expected: SKIPPED if no `DATABASE_URL`; if `DATABASE_URL` set, FAIL with `AttributeError: 'SupabaseClient' object has no attribute 'upsert_conversation'`.

- [ ] **Step 3: Add the methods to `db/supabase_client.py`**

Insert after `get_artifact` (the method ending at the `return None` for artifacts), before `def health`:

```python
    # ----------------------------------------------------------- conversations
    def upsert_conversation(self, conv: dict) -> bool:
        if not self.enabled:
            return False
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversations
                        (id, topic_id, run_id, title, summary, archived_count, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s, now())
                    ON CONFLICT (id) DO UPDATE SET
                        title=EXCLUDED.title, summary=EXCLUDED.summary,
                        archived_count=EXCLUDED.archived_count, updated_at=now()
                    """,
                    (conv["id"], conv["topic_id"], conv["run_id"],
                     conv.get("title", "New chat"), conv.get("summary", ""),
                     int(conv.get("archived_count", 0))),
                )
            return True
        except (psycopg2.Error, KeyError) as exc:
            log.error("upsert_conversation(%s) failed: %s", conv.get("id"), exc)
            return False

    def insert_message(self, conversation_id: str, role: str, content: str,
                       metadata: dict | None = None) -> bool:
        if not self.enabled:
            return False
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO messages (conversation_id, role, content, metadata) "
                    "VALUES (%s,%s,%s,%s)",
                    (conversation_id, role, content,
                     psycopg2.extras.Json(metadata or {})),
                )
            return True
        except psycopg2.Error as exc:
            log.error("insert_message(%s) failed: %s", conversation_id, exc)
            return False

    def get_conversation(self, conv_id: str) -> dict | None:
        if not self.enabled:
            return None
        try:
            with self._conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, topic_id, run_id, title, summary, archived_count "
                    "FROM conversations WHERE id=%s",
                    (conv_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
        except psycopg2.Error as exc:
            log.error("get_conversation(%s) failed: %s", conv_id, exc)
            return None

    def get_messages(self, conv_id: str) -> list[dict]:
        if not self.enabled:
            return []
        try:
            with self._conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT role, content, metadata, "
                    "extract(epoch from created_at)::bigint AS ts "
                    "FROM messages WHERE conversation_id=%s ORDER BY created_at, id",
                    (conv_id,),
                )
                return [dict(r) for r in cur.fetchall()]
        except psycopg2.Error as exc:
            log.error("get_messages(%s) failed: %s", conv_id, exc)
            return []

    def list_conversations(self, topic_id: str) -> list[dict]:
        if not self.enabled:
            return []
        try:
            with self._conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT c.id, c.title,
                           extract(epoch from c.created_at)::bigint AS created,
                           extract(epoch from c.updated_at)::bigint AS updated,
                           (SELECT count(*) FROM messages m
                              WHERE m.conversation_id = c.id) AS message_count
                    FROM conversations c
                    WHERE c.topic_id = %s
                    ORDER BY c.updated_at DESC
                    """,
                    (topic_id,),
                )
                return [dict(r) for r in cur.fetchall()]
        except psycopg2.Error as exc:
            log.error("list_conversations(%s) failed: %s", topic_id, exc)
            return []

    def delete_conversation(self, conv_id: str) -> bool:
        if not self.enabled:
            return False
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM conversations WHERE id=%s", (conv_id,))
                return cur.rowcount > 0
        except psycopg2.Error as exc:
            log.error("delete_conversation(%s) failed: %s", conv_id, exc)
            return False
```

- [ ] **Step 4: Run the test (DB) / confirm import (no DB)**

Run (with DB): `DATABASE_URL=... .venv/bin/python -m pytest tests/test_supabase_chat.py -v` → Expected: PASS.
Run (no DB): `.venv/bin/python -c "from db.supabase_client import SupabaseClient; print(hasattr(SupabaseClient,'upsert_conversation'))"` → Expected: `True`.

- [ ] **Step 5: Commit**

```bash
git add db/supabase_client.py tests/test_supabase_chat.py
git commit -m "feat(db): SupabaseClient conversation + message persistence"
```

---

## Task 3: chat_store dual-write + working-set reconstruction

**Files:**
- Modify: `lib/chat_store.py`
- Modify: `tests/test_chat_store.py`

Helpers used: `lib/store.py` exposes `read_json(run_id, name)` (line 97) and `_slug(text)` (line 22). `lib/chat_store.py` already does `from . import store`.

- [ ] **Step 1: Write the failing dual-write test**

Add to `tests/test_chat_store.py`:

```python
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

    # conversation upserted, both messages persisted append-only
    assert fake.convs[thread["id"]]["title"] == "hi?"
    assert [m["role"] for m in fake.msgs[thread["id"]]] == ["user", "assistant"]

    # DB-first working-set read (archived_count=0 → full set)
    loaded = chat_store.load_thread("run1", thread["id"])
    assert [m["content"] for m in loaded["messages"]] == ["hi?", "hello"]

    # list_threads resolves topic_id and reads DB
    rows = chat_store.list_threads("run1")
    assert rows[0]["id"] == thread["id"]


def test_working_set_skips_archived(tmp_path, monkeypatch):
    from lib import chat_store, store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(store, "read_json", lambda rid, name: {"topic_id": "t"})
    fake = _FakePg()
    monkeypatch.setattr(chat_store, "_pg", lambda: fake)
    # 3 full turns in DB, 1 turn already archived
    fake.convs["c1"] = {"id": "c1", "topic_id": "t", "run_id": "run1",
                        "title": "x", "summary": "S", "archived_count": 1}
    for i in range(3):
        fake.msgs.setdefault("c1", [])
        fake.msgs["c1"].append({"role": "user", "content": f"u{i}", "metadata": {}})
        fake.msgs["c1"].append({"role": "assistant", "content": f"a{i}", "metadata": {}})

    ws = chat_store.load_thread("run1", "c1")
    # archived_count=1 → skip first 2 messages
    assert [m["content"] for m in ws["messages"]] == ["u1", "a1", "u2", "a2"]
    assert ws["summary"] == "S"


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
```

- [ ] **Step 2: Run — verify failures**

Run: `.venv/bin/python -m pytest tests/test_chat_store.py -v`
Expected: FAIL — `new_thread` has no `topic_id`, `chat_store._pg` missing.

- [ ] **Step 3: Rewrite `lib/chat_store.py`**

Replace the whole file with:

```python
"""Per-thread chat persistence: file (memory working-set + fallback) plus a
Supabase dual-write that is the durable source of truth when enabled.

File path: data/runs/<run_id>/chats/<thread_id>.json (via lib.store.ROOT).
DB: `conversations` (title/summary/archived_count) + append-only `messages`.
Memory compaction (lib.chat_memory) only trims the file working-set; the DB
keeps full history. The answering path reconstructs the compacted working-set
from the DB so memory logic stays unchanged.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from . import store


def _pg():
    """Process-wide Supabase singleton, or None when the DB layer is absent."""
    try:
        from db import get_supabase
        return get_supabase()
    except ImportError:
        return None


def _topic_id(run_id: str) -> str:
    run = store.read_json(run_id, "run.json") or {}
    return run.get("topic_id") or store._slug(run.get("topic", "")) or run_id


def _conv_row(thread: dict) -> dict:
    return {
        "id": thread["id"],
        "topic_id": thread.get("topic_id") or _topic_id(thread["run_id"]),
        "run_id": thread["run_id"],
        "title": thread.get("title", "New chat"),
        "summary": thread.get("summary", ""),
        "archived_count": int(thread.get("archived_count", 0)),
    }


def _chats_dir(run_id: str) -> Path:
    p = store.ROOT / run_id / "chats"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _thread_path(run_id: str, thread_id: str) -> Path:
    return store.ROOT / run_id / "chats" / f"{thread_id}.json"


def new_thread(run_id: str, title: str = "New chat") -> dict[str, Any]:
    now = int(time.time())
    return {
        "id": uuid.uuid4().hex[:12],
        "run_id": run_id,
        "topic_id": _topic_id(run_id),
        "title": title,
        "created": now,
        "updated": now,
        "summary": "",
        "archived_count": 0,
        "messages": [],
    }


def append_message(thread: dict, role: str, content: str, *,
                   citations_detail: list | None = None,
                   confidence: float | None = None) -> dict:
    msg: dict[str, Any] = {"role": role, "content": content, "ts": int(time.time())}
    if citations_detail is not None:
        msg["citations_detail"] = citations_detail
    if confidence is not None:
        msg["confidence"] = confidence
    thread["messages"].append(msg)

    pg = _pg()
    if pg and pg.enabled:
        meta: dict[str, Any] = {}
        if citations_detail is not None:
            meta["citations_detail"] = citations_detail
        if confidence is not None:
            meta["confidence"] = confidence
        pg.upsert_conversation(_conv_row(thread))  # idempotent; ensures FK
        pg.insert_message(thread["id"], role, content, meta)
    return msg


def save_thread(thread: dict) -> None:
    thread["updated"] = max(int(thread.get("updated", 0)), int(time.time()))
    path = _thread_path(thread["run_id"], thread["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(thread, default=str, indent=2))

    pg = _pg()
    if pg and pg.enabled:
        pg.upsert_conversation(_conv_row(thread))


def _msgs_from_db(rows: list[dict], *, with_meta: bool) -> list[dict]:
    out = []
    for m in rows:
        d: dict[str, Any] = {"role": m["role"], "content": m["content"]}
        meta = m.get("metadata") or {}
        if with_meta:
            if "citations_detail" in meta:
                d["citations_detail"] = meta["citations_detail"]
            if "confidence" in meta:
                d["confidence"] = meta["confidence"]
        out.append(d)
    return out


def load_thread(run_id: str, thread_id: str) -> dict | None:
    """Compacted working-set for the answering/memory path (DB-first)."""
    pg = _pg()
    if pg and pg.enabled:
        conv = pg.get_conversation(thread_id)
        if conv:
            archived = int(conv.get("archived_count", 0))
            rows = pg.get_messages(thread_id)[archived * 2:]
            return {
                "id": conv["id"], "run_id": conv["run_id"],
                "topic_id": conv["topic_id"], "title": conv["title"],
                "summary": conv.get("summary", ""), "archived_count": archived,
                "messages": _msgs_from_db(rows, with_meta=False),
            }
    path = _thread_path(run_id, thread_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_thread_full(run_id: str, thread_id: str) -> dict | None:
    """Full history for display (DB-first); file fallback returns the working-set."""
    pg = _pg()
    if pg and pg.enabled:
        conv = pg.get_conversation(thread_id)
        if conv:
            rows = pg.get_messages(thread_id)
            return {
                "id": conv["id"], "title": conv["title"],
                "summary": conv.get("summary", ""),
                "archived_count": int(conv.get("archived_count", 0)),
                "messages": _msgs_from_db(rows, with_meta=True),
            }
    return load_thread(run_id, thread_id)


def list_threads(run_id: str) -> list[dict]:
    pg = _pg()
    if pg and pg.enabled:
        return pg.list_conversations(_topic_id(run_id))
    chats = store.ROOT / run_id / "chats"
    if not chats.exists():
        return []
    rows: list[dict] = []
    for f in chats.glob("*.json"):
        try:
            t = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        rows.append({
            "id": t.get("id", f.stem),
            "title": t.get("title", "Chat"),
            "created": t.get("created", 0),
            "updated": t.get("updated", 0),
            "message_count": len(t.get("messages", [])),
        })
    rows.sort(key=lambda r: r["updated"], reverse=True)
    return rows


def delete_thread(run_id: str, thread_id: str) -> bool:
    pg = _pg()
    db_deleted = bool(pg and pg.enabled and pg.delete_conversation(thread_id))
    path = _thread_path(run_id, thread_id)
    file_deleted = path.exists()
    if file_deleted:
        path.unlink()
    return db_deleted or file_deleted
```

- [ ] **Step 4: Run the tests — verify pass**

Run: `.venv/bin/python -m pytest tests/test_chat_store.py -v`
Expected: PASS (all tests, including pre-existing).

- [ ] **Step 5: Commit**

```bash
git add lib/chat_store.py tests/test_chat_store.py
git commit -m "feat(chat): dual-write chat history to Supabase with file fallback"
```

---

## Task 4: Server — full-history loader on thread GET

**Files:**
- Modify: `server.py` (the `/chat/thread/<thread_id>` GET branch, ~lines 686–699)

- [ ] **Step 1: Swap `load_thread` → `load_thread_full` in the GET branch**

In `chat_thread`, replace:

```python
    thread = chat_store.load_thread(run_id, thread_id)
    if thread is None:
        return jsonify({"error": "not found"}), 404
    if request.args.get("debug") == "1":
        return jsonify(thread)
    return jsonify({"id": thread["id"], "title": thread["title"],
                    "messages": thread["messages"], "summary": thread.get("summary", ""),
                    "archived_count": thread.get("archived_count", 0)})
```

with:

```python
    thread = chat_store.load_thread_full(run_id, thread_id)
    if thread is None:
        return jsonify({"error": "not found"}), 404
    if request.args.get("debug") == "1":
        return jsonify(thread)
    return jsonify({"id": thread["id"], "title": thread["title"],
                    "messages": thread["messages"], "summary": thread.get("summary", ""),
                    "archived_count": thread.get("archived_count", 0)})
```

(`/chat/ask` keeps `chat_store.load_thread` for the memory working-set — do not change it.)

- [ ] **Step 2: Verify server imports + route registers**

Run: `.venv/bin/python -c "import server; print('/chat/thread/<thread_id>' in [str(r) for r in server.app.url_map.iter_rules()])"`
Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add server.py
git commit -m "feat(chat): serve full history on thread GET (DB source of truth)"
```

---

## Task 5: Chat page — back→#/app + conversation_id persistence

**Files:**
- Modify: `templates/chat.html`

- [ ] **Step 1: Fix the back link (line 202)**

Replace:

```html
    <a class="icon-btn" href="/" title="Back to dashboard">←</a>
```

with:

```html
    <a class="icon-btn" href="/#/app" title="Back to dashboard">←</a>
```

- [ ] **Step 2: Persist active thread_id in the URL + localStorage**

In the `<script>`, add a helper after `const state = {...}` (line 242):

```javascript
function setActiveThread(id){
  state.thread = id;
  try {
    if (id) localStorage.setItem("pulsetrace_chat_thread", id);
    else localStorage.removeItem("pulsetrace_chat_thread");
  } catch(e){}
  const u = new URL(location.href);
  if (id) u.searchParams.set("thread_id", id); else u.searchParams.delete("thread_id");
  history.replaceState(null, "", u);
}
```

- [ ] **Step 3: Route all `state.thread = …` assignments through the helper**

Replace each of these:
- in `newChat()`: `state.thread = null;` → `setActiveThread(null);`
- in `openThread(id)`: `state.thread = id;` → `setActiveThread(id);`
- in `sendMessage()` stream handler: `if (ev.type === "meta"){ state.thread = ev.thread_id; }` → `if (ev.type === "meta"){ setActiveThread(ev.thread_id); }`

- [ ] **Step 4: Rehydrate the active thread on load**

At the end of `selectRun(runId)` (currently calls `newChat()` last), replace:

```javascript
  await loadSuggestions();
  newChat();
```

with:

```javascript
  await loadSuggestions();
  await loadThreads();
  let want = new URLSearchParams(location.search).get("thread_id");
  if (!want) { try { want = localStorage.getItem("pulsetrace_chat_thread"); } catch(e){} }
  if (want) { await openThread(want); }
  else { newChat(); }
```

Note: `openThread` falls back gracefully — if the stored id 404s it returns early, leaving the empty state; call `newChat()` from inside that guard. Update `openThread`'s early return:

```javascript
  if (!t || t.error) { newChat(); return; }
```

- [ ] **Step 5: Manual smoke test**

Run: `.venv/bin/python server.py` then in a browser:
1. Open `/chat`, send a message → URL gains `?thread_id=…`.
2. Reload the page → the conversation rehydrates (not a blank new chat).
3. Click `←` → lands on `/#/app` (dashboard app view, not landing).

Expected: all three hold.

- [ ] **Step 6: Commit**

```bash
git add templates/chat.html
git commit -m "feat(chat): persist conversation_id across reload; back to #/app"
```

---

## Task 6: Dashboard — remove inline ask, prominent Chat entry, same-tab open

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 1: Make the nav Chat entry prominent (line 678)**

Replace:

```html
    <span class="nav-back" onclick="openChat()" style="margin-left:12px">💬 Chat</span>
```

with:

```html
    <button class="nav-chat-cta" onclick="openChat()" title="Open conversational RAG workspace">💬 Chat (RAG)</button>
```

Add this CSS next to the `header .nav-back` rule (after line 162):

```css
header .nav-chat-cta {
  margin-left: 12px; display: inline-flex; align-items: center; gap: 6px;
  font-family: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
  color: #fff; background: var(--accent2); border: 1px solid var(--accent2);
  border-radius: 9px; padding: 7px 13px; transition: filter .15s ease, transform .15s ease;
}
header .nav-chat-cta:hover { filter: brightness(1.08); transform: translateY(-1px); }
```

(Because the Chat button now sits first after `← home`/`⚙ BYOK`, keep `← home` as the `margin-left:auto` spacer — unchanged.)

- [ ] **Step 2: Replace the inline ask panel (lines 881–889) with a Chat CTA card**

Replace:

```html
      <div class="panel">
        <h2>Ask about what people said</h2>
        <div class="row">
          <input id="q" placeholder="Ask anything about the posts we found..." style="flex:1" />
          <button id="ask-btn">Ask</button>
          <button class="secondary" onclick="openChat()" title="Open a full conversational workspace for this run">Open in Chat →</button>
        </div>
        <div id="answer" class="answer" style="margin-top:16px"></div>
      </div>
```

with:

```html
      <div class="panel chat-cta-panel">
        <h2>Ask about what people said</h2>
        <p class="muted" style="margin:0 0 14px">Open the conversational workspace to ask follow-up questions across this run's posts — every answer cites its evidence.</p>
        <button class="cta-primary" onclick="openChat()" title="Open conversational RAG workspace">💬 Open Chat (RAG) →</button>
      </div>
```

- [ ] **Step 3: Make `openChat()` navigate in the same tab (lines 1097–1100)**

Replace:

```javascript
function openChat() {
  const rid = runId || (function(){ try { return localStorage.getItem("pt:lastRunId"); } catch(e){ return null; } })();
  window.open(rid ? ("/chat?run_id=" + encodeURIComponent(rid)) : "/chat", "_blank");
}
```

with:

```javascript
function openChat() {
  const rid = runId || (function(){ try { return localStorage.getItem("pt:lastRunId"); } catch(e){ return null; } })();
  location.href = rid ? ("/chat?run_id=" + encodeURIComponent(rid)) : "/chat";
}
```

- [ ] **Step 4: Remove the dead `ask()` handler and its listeners**

Delete the entire `async function ask() { … }` block (lines ~2417–2446).
Delete these two listener lines (~2682–2683):

```javascript
$("#ask-btn").addEventListener("click", ask);
$("#q").addEventListener("keydown", e => { if (e.key === "Enter") ask(); });
```

(Leave `renderAnswerWithCites` / `renderCiteCard` in place — they may be referenced elsewhere; only `ask()` and its two listeners are removed.)

- [ ] **Step 5: Verify no remaining references to removed ids/functions**

Run: `grep -nE "\\bask\\(|#ask-btn|getElementById\\(.q.\\)|\\$\\(.#q.\\)|#answer\b" templates/index.html`
Expected: no matches for `ask(`, `#ask-btn`; `#q`/`#answer` only inside the deleted region (none should remain). If any match remains, remove it.

- [ ] **Step 6: Manual smoke test**

Run: `.venv/bin/python server.py`, open `/#/app`:
1. Header shows a filled **💬 Chat (RAG)** button (visually prominent).
2. The "Ask about what people said" panel shows the CTA card, no text input.
3. Clicking either Chat entry navigates **same tab** to `/chat?run_id=…`.
4. No console errors (the removed `ask` listeners don't throw).

Expected: all hold.

- [ ] **Step 7: Commit**

```bash
git add templates/index.html
git commit -m "feat(ui): prominent Chat (RAG) entry; remove inline ask; same-tab open"
```

---

## Task 7: Full verification

- [ ] **Step 1: Run the whole suite (mocked default)**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (chat_store dual-write + fallback green; supabase_chat skipped without `DATABASE_URL`).

- [ ] **Step 2: Live DB pass (if provisioned)**

Run: `DATABASE_URL=<supabase> .venv/bin/python -m pytest tests/test_supabase_chat.py -v`
Expected: PASS, conversation roundtrip + FK cascade verified.

- [ ] **Step 3: End-to-end manual check with DB enabled**

With `DATABASE_URL` set and schema applied, run the server, open `/chat`, send 2–3 messages, reload → history restored **from Supabase** (delete the local `data/runs/<id>/chats/*.json` first to prove DB is the source). Confirm rows in `conversations` + `messages`.

- [ ] **Step 4: Final commit / open PR**

```bash
git push -u origin feat/chat-persistence
```
PR base = `shyan` (per project convention).

---

## Self-Review notes

- **Spec coverage:** schema (T1), Supabase methods (T2), dual-write + memory-preserving reconstruction (T3), full-history serve (T4), back→#/app + conversation_id persistence (T5), prominent Chat entry + remove inline ask + same-tab (T6). Summarization untouched (`chat_memory.py` not modified; verified by leaving `tests/test_chat_memory.py` unchanged and green).
- **Working-set invariant:** `load_thread` returns `get_messages()[archived_count*2:]`, reconstructing the exact file working-set because compaction always trims complete leading user/assistant pairs (`cut = overflow_turns*2`) and only user/assistant messages are appended.
- **FK ordering:** `append_message` upserts the conversation before inserting messages, so the first message of a brand-new thread never violates the FK.
- **Fallback:** every `SupabaseClient` method and every `chat_store` DB branch is guarded by `enabled` / `_pg() is not None`, so a cold demo (no `DATABASE_URL`) runs unchanged on files.
