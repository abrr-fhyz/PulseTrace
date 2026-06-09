# Orchestration Layer — Decisions

Branch `feat/orchestration` (PR #13 → `shyan`). LangGraph + n8n + scheduling,
backing the submission claims that the gap audit flagged as unbuilt.

## What it is
An explicit, resumable **LangGraph** state graph that wraps the existing agent:
`crawl → score → alert/recover → done`. It adds engagement alerting,
failure-recovery retries, and scheduling hooks on top of the analysis pipeline.

- `lib/orchestration/state.py` — `AgentState` TypedDict (items, scores,
  retry_count, should_alert, error + topic/sources/run_id/opinion + summary).
- `lib/orchestration/nodes.py` — pure nodes; only `crawl` (runs the pipeline)
  and `alert` (n8n webhook) do IO, both swallow errors into state.
- `lib/orchestration/graph.py` — edges + `MemorySaver` (Sqlite/Redis swap documented).
- `lib/orchestration/runner.py` — drives `graph.stream`, republishes each node
  delta as `orch_started/orch_step/orch_done` on the SSE `BUS`.
- `lib/orchestration/config.py` — env knobs (AGENT_MAX_RETRIES, RETRY_BACKOFF,
  ENGAGEMENT_THRESHOLD, SQUASH_SCALE, N8N_WEBHOOK_BASE_URL, N8N_RECRAWL_CRON).
- `n8n/` — JSON workflow exports only (scheduled_recrawl, engagement_alert,
  failure_recovery) + README.

## Decisions
- **n8n = JSON exports only, no running instance / Docker.** Respects the
  project's no-Docker / no-hosted non-goal; artifacts still back the claim.
- **Engagement squash `1 - exp(-raw/SCALE)` (SCALE=3.0).** `influence()` is
  unbounded; squashing into 0–1 makes the 0.75 threshold meaningful. The one
  real business knob (env `AGENT_ENGAGEMENT_SQUASH_SCALE`).
- **mypy scoped to `lib/orchestration`** in `make verify`; rest of `lib/`
  predates type-checking. Widen later.
- **Plan B: `crawl` runs the FULL `run_agent`**, not a thin fetch. So
  orchestration adds alerting/retry/schedule ON TOP of cluster/label/sentiment/
  briefing/evidence — it produces the same rich outputs plus a summary, rather
  than a weaker parallel pipeline. `run_agent(close_bus=False)` keeps the SSE
  stream open so the graph's score/alert/done can still emit before `_close`.
- **Single search box.** The dashboard's existing "Run Agent" form now POSTs to
  `/api/agent/run` (was `/run`); the orchestration card is a live status panel
  (node timeline + result + alert), driven off the *same* SSE stream via
  `window.__orch.handle`. The old `/run` endpoint + `run_agent` stay intact but
  the UI no longer calls `/run`. Removed the duplicate orchestration search box.
- **`/api/agent/run` mirrors `/run`** for opinion + BYOK apply/restore.

## Data output
- `data/runs/<run_id>/orchestration_summary.json` →
  `{run_id, n_items, n_scored, max_score, clusters, has_briefing, retry_count, alerted, error}`.
- Plus full pipeline artifacts (posts/clusters/ranked/briefing/evidence) since
  `crawl` runs `run_agent`.
- Alert webhook payload to n8n: `{item_id, score, run_id}` when threshold tripped.

## Gotchas
- Keyless Reddit has zero engagement counts → influence is recency-only
  (max_score ≈ 0.07–0.14), so the alert never fires on Reddit. Use Facebook or
  PRAW-authed Reddit for meaningful engagement scoring.
- Two SSE consumers on one stream is fine (BUS supports multiple subscribers),
  but the UI uses a single EventSource and fans out to both the dashboard
  handler and `window.__orch.handle`.
