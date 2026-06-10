# Persistent Conversational Chat (Supabase source of truth)

> Design spec. 2026-06-10. Branch `feat/chat-persistence` (off `feat/prompting`).
> Status: approved, pending implementation plan.

## Goal

Persist all chat history (user + assistant + summary state) in Supabase as the
durable source of truth, while preserving the existing rolling-summary memory
logic exactly, and tightening the chat UI/UX + navigation.

## Context (current state)

- **Chat persistence is file-only**: `lib/chat_store.py` writes per-thread JSON to
  `data/runs/<run_id>/chats/<thread_id>.json`. Threads scoped to a `run_id` (its
  post corpus is the RAG evidence).
- **Memory**: `lib/chat_memory.py` keeps a rolling summary — last `RECENT_TURNS`
  pairs verbatim, older pairs folded into `thread["summary"]` via one LLM call.
  Must be preserved unchanged.
- **Supabase** (`db/supabase_client.py`, `db/schema.sql`) already holds
  runs/posts/clusters/run_artifacts. It is **additive + fallback-safe**: enabled
  only when `DATABASE_URL`/`SUPABASE_DB_URL` is set, else `enabled is False` and
  callers use file storage. No conversations/messages tables yet.
- **UI**: `templates/chat.html` is a dedicated chat page with a single bottom
  composer (correct). The duplicate input is the **dashboard** "Ask about what
  people said" panel (`index.html:881–889`): inline `#q` + Ask + an "Open in
  Chat" button that opens `/chat` in a **new tab**. chat.html back link is
  `href="/"` → lands on landing view, not `#/app`.
- **Routing**: dashboard SPA hash router `#/{landing,byok,app,shots}`; active run
  in `localStorage pt:lastRunId`.

## Decisions

| Question | Decision |
|---|---|
| Owner/identity (project non-goal: Auth) | Use **`topic_id`** as the owner/group key (the schema's `user_id` slot). |
| Supabase strictness | **Dual-write + file fallback.** Supabase = source of truth when enabled; file keeps cold demo working. |
| Open chat from dashboard | **Same tab** (so back→`#/app` is coherent). |
| Dashboard ask panel | **Replace with a prominent "Open Chat (RAG)" CTA card.** |
| Conversation grouping | List by **`topic_id`** so history survives re-runs of the same topic. |
| DB messages vs file memory | DB `messages` is **append-only full history**; file holds the compacted memory working-set. |

## Architecture

Mirror the existing `lib/store.py` additive pattern. File remains the in-flight
**memory working-state** and the **cold-demo fallback**; Supabase is the durable
record when enabled. `lib/chat_memory.py` is untouched.

```
chat_ask (server) ──> chat_store (dual-write) ──> file JSON  (memory working-set + fallback)
                                              └──> SupabaseClient (durable record, when enabled)
                                                     conversations  (title, summary, archived_count)
                                                     messages       (append-only full history)
```

### Schema (`db/schema.sql`, idempotent)

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id             text PRIMARY KEY,                 -- existing 12-hex thread id
    topic_id       text NOT NULL,                    -- owner/group key
    run_id         text NOT NULL,                    -- corpus the RAG retrieves against
    title          text NOT NULL DEFAULT 'New chat', -- auto from first question
    summary        text NOT NULL DEFAULT '',         -- rolling summary (memory preserved)
    archived_count integer NOT NULL DEFAULT 0,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_conversations_topic ON conversations (topic_id, updated_at DESC);
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS messages (
    id              bigserial PRIMARY KEY,
    conversation_id text NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            text NOT NULL,                   -- user | assistant | system
    content         text NOT NULL DEFAULT '',
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,  -- citations_detail, confidence, iterations
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_messages_convo ON messages (conversation_id, created_at);
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
```

### Persistence (`db/supabase_client.py` + `lib/chat_store.py`)

New `SupabaseClient` methods, all guarded by `if not self.enabled: return …`:

- `upsert_conversation(conv: dict) -> bool`
- `insert_message(conversation_id, role, content, metadata) -> bool`
- `get_conversation(conv_id) -> dict | None`
- `get_messages(conv_id) -> list[dict]`  (ordered by `created_at`)
- `list_conversations(topic_id) -> list[dict]`
- `delete_conversation(conv_id) -> bool`

`lib/chat_store.py` becomes dual-write while keeping its current file functions:

- `save_thread(thread)` → write file **and** `upsert_conversation` (title, summary,
  archived_count, updated_at). Needs `topic_id`; resolve from the run's `run.json`.
- `append_message(thread, role, content, …)` → append to file thread **and**
  `insert_message` (append-only; compaction never deletes DB rows).
- `load_thread(run_id, thread_id)` → **DB-first when enabled**: rebuild working
  thread = `{summary, archived_count}` from the conversation row + the recent
  messages from DB; file fallback otherwise. The full message list for **display**
  comes from `get_messages`.
- `list_threads(run_id)` → resolve `topic_id` from the run, then
  `list_conversations(topic_id)` when enabled; file glob fallback.

**Memory stays exact**: the reconstructed working thread feeds `chat_memory.compact`
and `build_preamble` with no changes to `chat_memory.py`.

### Title & summary storage

- `title` ← first user question (existing `q[:48]`), stored on the conversation row.
- `summary` ← the rolling summary, stored in the dedicated `conversations.summary`
  column (superset of the spec's "title or system message" option; no new
  system-message plumbing, memory logic unchanged).

### Server endpoints (`server.py`)

- `/chat/threads` (GET list): list by `topic_id` resolved from `run_id`.
- `/chat/thread/<id>` (GET): return full message history (DB `get_messages` when
  enabled, file fallback). DELETE cascades via FK.
- `/chat/ask` (SSE): unchanged flow; the post-stream save now dual-writes.

### UI — dashboard (`templates/index.html`)

- **Remove** the inline ask panel (`#q` input + `#answer`, lines 881–889);
  replace with a prominent **"Open Chat (RAG)" CTA card**.
- Add a **prominent chat icon** to the dashboard header nav (size + contrast +
  active-highlight; clearly the primary conversational action).
- `openChat()` → **same-tab** `location.href = "/chat?run_id=…"` (drop `_blank`).
- Remove the dead `ask()` handler + `#ask-btn`/`#q` keydown listeners.

### UI — chat page (`templates/chat.html`)

- Back `←` link → **`/#/app`** (restores existing app state, no reset).
- Persist active `conversation_id` in URL (`?thread_id=`) + localStorage; on load,
  **rehydrate from DB**. Deterministic resolution: `thread_id` present → reuse;
  else create new on first send. Single bottom composer already correct.

## Constraints honored

- Summarization prompt logic untouched (`lib/chat_memory.py` unchanged).
- Supabase is source of truth when enabled; never **only** local — file is a
  mirror/fallback, not the canonical store on a provisioned deployment.
- One unified chat input (chat page only); dashboard inline input removed.
- Back navigation restores `#/app`; no app-state reset, no new session.

## Out of scope

Auth/login, multi-device sync conflict resolution, editing/branching past
messages, migrating existing file-only threads into Supabase (new threads only;
old file threads still load via fallback).

## Testing

- `tests/test_chat_store.py`: extend for dual-write and DB-disabled fallback
  (mock `get_supabase()` returning an enabled stub; assert calls + assert file
  still written).
- New supabase conversation/message tests gated behind `DATABASE_URL`
  (`pytest.skipif`), mocked otherwise — mirror existing db test style.
- `tests/test_chat_memory.py` unchanged (proves memory logic preserved).
```
