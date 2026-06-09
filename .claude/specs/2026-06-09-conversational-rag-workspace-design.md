# Conversational RAG Workspace + Rolling Summary Memory — Design

> Date: 2026-06-09. Branch: `feat/prompting`. PR target: `shyan`.
> Status: approved design, implementing.

## Problem

RAG works (`lib/rag.py:ask` — hybrid retrieve + self-reflective loop) but interaction
is fragmented: the dashboard SPA exposes a one-shot `/ask` box, no dedicated space to
explore, refine, iterate. Each ask is stateless — no continuity across questions.

Also closes **Q-token-02 (rolling summary memory)** from
`.claude/specs/2026-06-09-token-optimization-audit.md`: previously audited as ABSENT.
This is its first real implementation.

## Goal

A standalone, production-grade chat workspace users prefer over raw search results,
plus a lightweight rolling-summary memory for long-conversation continuity.

## Architecture (backend)

Standalone route, not folded into the 2530-line `index.html` SPA. New small modules,
reuse `lib/store.py:ROOT`.

### Routes (`server.py`)
```
GET  /chat                      → templates/chat.html
GET  /chat/runs                 → [{run_id, topic, n_posts, when}]   run-switcher
GET  /chat/threads?run_id=      → thread list for a run
POST /chat/threads {run_id}     → {thread_id}
GET  /chat/thread/<tid>?run_id= → {messages, summary, archived_count}
DEL  /chat/thread/<tid>?run_id= → ok
POST /chat/ask  (SSE)           → stage events + answer; persists turn; runs compaction
```

### New modules
- **`lib/chat_store.py`** — per-thread JSON at `data/runs/<run_id>/chats/<tid>.json`.
  Schema:
  ```json
  {"id","run_id","title","created","updated",
   "summary":"", "archived_count":0,
   "messages":[{"role":"user|assistant","content":"...",
                "citations_detail":[...], "confidence":0.0, "ts":0}]}
  ```
  Functions: `new_thread`, `load_thread`, `save_thread`, `list_threads`,
  `delete_thread`, `append_message`. Reuses `store.ROOT`; empty/missing → safe defaults.

- **`lib/chat_memory.py`** — rolling summary.
  - `RECENT_TURNS = 6` kept verbatim. A "turn" = one user+assistant pair.
  - `compact(thread)`: when verbatim turns > `RECENT_TURNS`, fold the oldest overflow
    into `summary` via one `chat_json` call (capped ~150 tokens), bump `archived_count`,
    drop the archived messages from `messages`. Idempotent when under threshold.
  - `build_preamble(thread)` → str: `summary` + the recent verbatim Q/A, formatted for
    prepending to the RAG question. Empty thread → "".
  - Pure logic except the one summarizer call → TDD with mocked `chat_json`.

- **`lib/chat_engine.py`** — streaming orchestration.
  - `answer_stream(run_id, question, preamble) -> Iterator[dict]` yields SSE events:
    `{"stage":"retrieving","n":8}` → `{"stage":"drafting"}` →
    `{"stage":"verifying","confidence":0.82}` → (opt) `{"stage":"refining"}` →
    `{"type":"answer", "answer","citations_detail","confidence","iterations"}` →
    `{"type":"done"}`.
  - Reuses `rag` internals (`hybrid_search`, `ASK_SYS`/`JUDGE_SYS`/`REFINE_SYS`,
    `_citation_detail`, thresholds). The loop body is the same self-reflective logic,
    refactored to yield stage events instead of returning at the end.

### RAG change (minimal)
`rag.ask(run_id, question, k=8, *, preamble="")` — optional preamble prepended to the
question context. No behavior change when absent. Keeps the synchronous `/ask` path
intact; the chat path uses `chat_engine` for streaming.

## Streaming (SSE)

`/chat/ask` returns `text/event-stream` via `stream_with_context` (same pattern as
existing `/events`). Stage events are **honest** — they mirror the real loop. The final
answer arrives whole (strict-JSON), and the client does a short typewriter reveal
(cosmetic only; not true token streaming, since RAG returns parsed JSON).

## Rolling Summary Memory — evaluation

- **Fit:** clean. `ask()` stays stateless; memory is an external preamble. No RAG rewrite.
- **Tradeoffs:** preamble adds ~200 tokens/turn but caps unbounded transcript growth;
  net token saver on long threads. One extra summarizer call per compaction
  (every `RECENT_TURNS` turns), not per message.
- **Storage:** one small JSON per thread under the run dir. Negligible.
- **UX:** follow-ups / pronouns resolve across turns; continuity without context explosion.
- **Observability:** `summary` + `archived_count` persisted; `GET /chat/thread/<tid>?debug=1`
  returns them; UI "memory" peek shows current summary.

## Frontend (`templates/chat.html`)

Standalone page, **reuses existing `:root` theme tokens** (Inter, emerald `--accent`,
light default + `data-theme="dark"`). No build step — CDN `marked` + `DOMPurify` for
markdown only.

- **Layout:** header (`← Home`, title, run-switcher ▾, theme ☾) · collapsible thread
  sidebar (mobile drawer) · conversation · fixed composer.
- **Messages:** distinct user/assistant, generous whitespace, ~70ch width, markdown +
  code blocks, citation chips (reuse `.cite-card` styling) expanding to post preview +
  screenshot via `citations_detail`.
- **Composer:** auto-grow textarea, Enter=send / Shift+Enter=newline, send button,
  disabled+loading while streaming.
- **Empty state:** heading + 3 suggested prompts derived from the run's **cluster
  labels** (context-aware), quick-start actions.
- **Responsive:** sidebar → drawer < 768px.

## Navigation rationale

Standalone `/chat` chosen over a 5th SPA tab: a dedicated workspace reads as premium
(OpenAI/Claude/Perplexity-like) and stays decoupled from dashboard chrome. Run-switcher
= workspace switcher; thread sidebar = session continuity. No dead ends — persistent
`← Home`. Entry point: an **"Open in Chat →"** action on the dashboard results/RAG view
linking `/chat?run_id=<id>`.

## Testing
- `tests/test_chat_memory.py` — compaction trigger, summary merge, preamble build (mock `chat_json`).
- `tests/test_chat_store.py` — roundtrip, list, delete, empty-safe.
- Engine/endpoint smoke gated where it needs a real run.

## Out of scope (YAGNI)
- Auth / multi-user (project non-goal).
- Cross-run chat (RAG is per-corpus; run-switcher covers it).
- True token streaming (RAG returns parsed JSON; typewriter is cosmetic).

## Files
- new: `lib/chat_store.py`, `lib/chat_memory.py`, `lib/chat_engine.py`, `templates/chat.html`,
  `tests/test_chat_memory.py`, `tests/test_chat_store.py`
- edit: `lib/rag.py` (preamble param), `server.py` (routes), `templates/index.html`
  (entry button)

## Future enhancements
- Per-user memory + personalization (needs auth, out of current non-goals).
- Cache eviction for `embed_cache.jsonl` (open Q-token-04 tail).
- True streaming if RAG moves to incremental token output.
