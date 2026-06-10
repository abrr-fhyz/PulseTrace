# Run History + Routing Semantics — Design

Date: 2026-06-10
Branch: shyan

## Problem

Two coupled issues:

1. **Refresh / cold-load restores the last run.** An earlier fix made the
   dashboard rebuild the last run from `localStorage` on every cold load. Side
   effect: a plain page refresh (or any fresh visit) drops the user into stale
   results instead of a clean new search.
2. **Returning from chat lands on a blank dashboard.** `/chat` is a separate
   server-rendered page, so leaving the dashboard is a full browser navigation
   that destroys the live-painted DOM. The chat "back" link is `/#/app` with no
   run reference, so it can't restore the run the chat was about.

There is also no way to revisit past searches.

## Desired behavior

- `#/app` with **no** run ref → fresh run: blank dashboard, empty form.
- **Back from chat for run X** → returns to run X's dashboard.
- **Refresh / logo / Home** → fresh run (never auto-restore).
- **Past searches** list (history) → click restores that run.
- PulseTrace logo reads as clickable (hover affordance + tooltip) and starts a
  new search.

## Storage

Supabase is the source of truth; disk is the always-on fallback (the existing
additive + fallback pattern).

- The live `pulsetrace` Supabase project already has the `runs` table
  (`run_id, topic, topic_id, sources, status, started_at, finished_at,
  n_posts, meta`). It is already a run index — **no new schema**.
- `lib/store.py:_mirror_to_db` already upserts `run.json` → `runs` via
  `upsert_run`, so new runs persist to Supabase automatically now that
  `DATABASE_URL` is configured (session-mode pooler,
  `aws-1-ap-south-1.pooler.supabase.com:5432`).
- The 187 pre-existing disk runs are not in the DB; a one-time backfill seeds
  them.

### Known data nit

`_mirror_to_db` builds `RunRecord.n_posts` from `run.get("n_posts")`, but runs
persist the count under `metrics.posts`. Result: DB `n_posts` is 0. Fix the
mirror to read `metrics.posts` as a fallback.

## Components

### Backend

- `db/supabase_client.py` → `list_runs(limit=50) -> list[dict]`
  `SELECT run_id, topic, started_at, finished_at, n_posts, status
   FROM runs ORDER BY started_at DESC NULLS LAST LIMIT %s`.
- `server.py` → `GET /runs`
  - If `get_supabase().enabled` and `list_runs` returns rows → use them.
  - Else scan `data/runs/*/run.json` (disk fallback).
  - Normalize to `[{run_id, topic, started_at, finished_at, n_posts}]`,
    newest first.
- Backfill: iterate `data/runs/*/run.json`, upsert each into `runs`.

### Frontend — `templates/index.html`

- Remove cold-load auto-restore. Restore fires **only** on an explicit run ref.
- Boot: read `run` from the hash query (`#/app?run=<id>`). If present →
  `restoreRun(id)`, then `history.replaceState` to `#/app` so a later refresh is
  a fresh run.
- `newRun()` helper: clear `#clusters`, destroy charts/graph, reset metrics,
  hide `#voices`/`#evidence`/briefing link, clear `#topic`, null `runId`.
- Left **"Past searches"** sidebar panel (collapsible) in the app view, themed
  with CSS tokens (dark default). Fetch `/runs`, render topic + relative time,
  click → navigate to `#/app?run=<id>` restore path.
- Logo: pointer cursor, hover glow/underline, `title="Start a new search"`,
  click → `newRun()` + `goto('app')`.

### Frontend — `templates/chat.html`

- Back link `/#/app` → `/#/app?run=${state.run}`.

## Data flow

```
search ─► /api/agent/run ─► SSE paints dashboard ─► run.json written
                                                     └► store mirror ─► Supabase runs
chat link ─► /chat?run_id=X
back ─────► /#/app?run=X ─► restoreRun(X) via /run-info ─► strip ?run
sidebar ──► GET /runs ─► click row ─► #/app?run=X ─► restoreRun(X)
logo ─────► newRun() ─► blank #/app
```

## Error handling

- `/runs`: DB error or disabled → disk fallback; disk error → `[]`.
- `restoreRun`: missing/invalid run → leave dashboard blank (no throw).
- Backfill: best-effort per run; skip + log failures, never abort the batch.

## Testing / verification

- `list_runs` returns rows from live Supabase after backfill.
- `GET /runs` returns newest-first list (DB path and disk-fallback path).
- Browser: cold load `#/app` → blank; `#/app?run=<id>` → restored then URL
  stripped; refresh after restore → blank; sidebar click → restore; logo click
  → blank; chat back → correct run.

## Non-goals

- No new Supabase tables. No Mongo (explicitly skipped).
- No pagination / search within history (recent N only).
- No auth.
