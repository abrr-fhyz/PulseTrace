# Real MCP Server — 14 Tools Wired to Codebase

**Date:** 2026-06-09
**Branch:** `feat/real_mcp` (base `shyan`)
**Status:** approved design

## Problem

PR `feat/real_mcp` shipped 14 FastMCP tools that are pure stubs returning
hardcoded mock data, on a non-installed `fastmcp` dependency, with a composition
hack (`server._tools` merge) that crashes at import, and overwrites `main.py`
(the v1 CLI). None of the tools touch the real PulseTrace pipeline.

Goal: deliver the same 14-tool surface, but every tool wired to real `lib/`
functions and real per-run data. No mock data anywhere. Keep the v1 CLI intact.

## Decisions

- **MCP stack:** official `mcp` SDK (`mcp.server.fastmcp.FastMCP`) — already
  installed, existing `mcp_server.py` proven on it. Drop standalone `fastmcp`.
- **Composition:** one `FastMCP` instance, tools registered via `register(mcp)`
  per module. No `_tools` merge, no `import_server`/`mount` needed.
- **Return types:** plain `dict` (matches existing tools + coding standard
  "no Pydantic for output"). Unknown run → `{"error": ...}`, never raise.
- **Scope of the 5 unbacked tools:** build real backing for all of them.
- **`main.py`:** untouched. MCP entrypoint stays `mcp_server.py`.

## Architecture

```
mcp_server.py                 one FastMCP("PulseTrace"); calls register() per module
lib/mcp/__init__.py
lib/mcp/schema.py             PostSchema + validate_posts() → real pass-rate report
lib/mcp/data_tools.py         Group A (crawl control) + B (data access); register(mcp)
lib/mcp/intelligence_tools.py Group C (inference) + D (admin); register(mcp)
lib/agent.py                  + cancel-flag check in run_agent loop
lib/store.py                  + cancel-flag helpers: request_cancel/is_cancelled/clear_cancel
tests/test_mcp_tools.py       real seeded run, no mocks
```

`session_id` is the existing `run_id`. The "crawl session" vocabulary maps onto
the run model; no parallel concept is introduced.

## Tool → backing map

| # | Tool | Backing |
|---|------|---------|
| A1 | `start_crawl_session(topic, sources=None)` | `new_run_id()` + daemon-thread `run_agent` |
| A2 | `get_crawl_status(session_id)` | `_run_status` + run.json (status, posts, iters, stop_reason, started/finished). Real fields only — no fabricated worker_count/ETA |
| A3 | `cancel_crawl_session(session_id)` | `store.request_cancel`; agent loop checks each iter → `stop_reason="cancelled"` |
| A4 | `list_crawl_sessions(page=1, limit=10)` | iterate `store.ROOT`, sort by started_at, paginate |
| B5 | `get_posts_by_session(session_id, keyword=None, min_engagement=0)` | posts.json; filter keyword in text, `influence()` ≥ min |
| B6 | `get_post_detail(post_id, session_id=None)` | locate in given run or scan runs; full record + raw |
| B7 | `get_top_posts(session_id, limit=5)` | `influence.top_n` over `Post(**p)` |
| B8 | `get_keyword_summary(session_id)` | clusters.json → per-cluster label, size, sentiment dist |
| C9 | `run_inference(session_id)` | `briefing.build(with_pdf=False)` + persist `inference.json` (exec summary, top users via `influence`) |
| C10 | `get_inference_result(session_id)` | read `inference.json` (run C9 if absent) |
| C11 | `query_rag(session_id, query)` | `rag.ask` |
| C12 | `get_sentiment_breakdown(session_id)` | clusters.json tally → overall dist + confidence from sample sizes |
| D13 | `get_schema_validation_report(session_id)` | `schema.validate_posts(posts.json)` → real pass_rate, failed_fields, error_types |
| D14 | `trigger_enrichment_batch(session_id)` | recompute `engagement_score`+per-post sentiment for posts missing them; persist to posts.json |
| +15 | `detect_coordination(session_id, min_authors=3)` | existing `coordination.detect_campaigns` (kept — unique) |

**Folded (overlap removed):** `analyze_topic`→A1, `ask_corpus`→C11, `get_run`→A2/C10.

## Real-backing details for previously-mock tools

- **Cancel (A3):** `lib/store.py` gains `request_cancel(run_id)` (touch
  `<run_dir>/cancel.flag`), `is_cancelled(run_id)`, `clear_cancel(run_id)`.
  `run_agent` checks `is_cancelled` at the top of its `for it in range(MAX_ITERS)`
  loop; if set, `stop_reason="cancelled"`, break, persist. Flag cleared on run
  start. Cooperative cancellation — no thread kill.
- **get_post_detail (B6):** posts are per-run. With `session_id`, read that
  run's posts.json; without, scan `ROOT` runs for matching `id`. Returns the
  full dict including `raw`. Not found → `{"error": "no such post"}`.
- **run_inference / get_inference_result (C9/C10):** C9 calls
  `briefing.build(run_id, with_pdf=False)`, then derives
  `{executive_summary, consensus_narrative, top_users}` from clusters +
  `influence.top_n` authors, writes `inference.json`. C10 reads it; if missing,
  invokes C9 first. Executive summary from briefing's real LLM `_exec_summary`.
- **schema validation (D13):** `PostSchema` dataclass mirrors `Post` required
  fields/types. `validate_posts(posts)` returns `pass_rate`, `failed_fields`
  (field→count), `error_types`. Counts are real, computed over posts.json.
- **enrichment (D14):** load posts.json, build `Post(**p)`, compute
  `engagement_score = influence()`; per-post sentiment via `stance.score_batch`
  using run topic as theme; write enriched fields back. Returns count enriched
  (only posts lacking the fields are processed; idempotent).

## Error handling

- Every tool: unknown/missing run → `{"error": "..."}` dict; never raise.
- Connector/LLM failures inside `run_agent` already swallowed by the loop.
- Empty inputs → empty results (`[]`, `{}`), not errors (coding standard).

## Testing

`tests/test_mcp_tools.py`, no mock data:
- Seed (or reuse) a real run under `data/runs` with posts.json + clusters.json.
- Assert each read tool returns real values from those files.
- `validate_posts` tested on a known-good and a known-bad record set.
- Cancel: assert flag set/cleared via `store` helpers and agent honors it.
- Schema/enrichment tested as pure functions where possible (TDD).

## Out of scope

- Worker pools / true parallel crawl (status reports real single-run state).
- DB-backed sessions (file store only, per existing `store.py`).
