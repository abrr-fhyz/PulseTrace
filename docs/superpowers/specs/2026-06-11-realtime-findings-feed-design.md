# Live-Building Dashboard (Real-Time Results) — Design

> Status: approved (design, revised). Branch: `feat/realtime`.
> Date: 2026-06-11
> Supersedes the earlier "findings feed → handoff" direction.

## Problem

A run shows a full-screen loader overlay (`PL2`, `static/js/pipeline.js`) with a
**fake stage timer** for its entire duration (~2–6 min), then reveals the whole
dashboard at once when `done` fires. The wait feels like nothing is happening,
and the actual results only land at the end.

Crucially, the dashboard **already builds in real time** under that overlay:
- `static/js/agent.js` `handle()` bumps KPIs (`#m-posts`, `#m-clusters`,
  `#m-entropy`) on each event,
- redraws the sentiment chart (`renderSentChart`) and the talking-points /
  opinions list (`renderClusters`) on every `labeled` / `reranked`,
- draws the topic graph at `done` (`drawGraph`),
- the sidebar **Pipeline** card (`.pl-stage` in `_app_left.html`, driven by the
  `pl*` helpers) already tracks live stage progress.

All of it is **hidden behind the `PL2` overlay** until `done`. The fake timer is
also the source of the earlier "count stuck at 0" and "badge overlaps stages"
bugs.

## Goal

Make the results **build in front of the user in real time**, ChatGPT-style:
remove the blocking overlay so the dashboard is visible from the start; KPIs
climb, the sentiment chart draws, opinions/talking points stream in one by one
with a **typed-text effect**, and the graph renders — as each result is actually
produced. Skeleton placeholders fill the gap before first data so nothing looks
broken or empty.

Non-goals: changing the backend agent loop or the SSE event schema; real
token-by-token streaming of the briefing text (would need backend SSE token
events — deferred). This is a presentation-layer change to the dashboard reveal.

## UX

```
On run start (no overlay — dashboard visible):
  Pipeline:  ● Seed queries      working…
  Metrics:   Posts 0   Topics 0   Spread --
  Main talking points:  [▒▒▒▒▒]  [▒▒▒]  [▒▒▒▒]   (skeleton shimmer)
  Graph panel: "Building the graph as posts come in…"

As events arrive (live, no reload):
  Posts 12 → 47 → 115         (KPIs climb)
  Sentiment chart fades in and redraws
  ▸ Life of Pi meanings (39)  ← label types in char-by-char, card rises in
  ▸ VFX industry (6)          ← next one types in
  Spread 1.83
  (on done) topic graph renders, briefing/voices/evidence panels fade in
```

- No full-screen overlay. The existing dashboard is the UI.
- Each new talking point (opinion) **types in** character-by-character and the
  card slides/fades up. Re-renders (on `reranked`) update existing cards
  instantly — only genuinely new labels type in (no flicker / re-typing).
- Skeleton shimmer placeholders show in the talking-points list until the first
  real clusters arrive.
- `prefers-reduced-motion`: typing and rise animations collapse to instant.

## Architecture

Presentation-only. Remove the `PL2` overlay entirely; lean on the dashboard
renderers that already run live in `handle()`. Add three things: skeletons,
a typed-label effect, and panel reveal animation.

### Removed
- The entire `PL2` IIFE in `static/js/pipeline.js` (lines 32–397): `startSim`,
  `APPROX`, `setStage`/`setMin`, `renderAnim`, `buildRail`/`paintRail`,
  `paintCount` + `pl2-livecount`, reassure/eta timers, confetti, the fake stage
  STAGES array — all of it.
- `PL2.start()` and `PL2.event(ev)` calls in `agent.js`.
- The `#pl2` overlay markup in `templates/partials/_loader.html`.

### Kept (already live, no change to behavior)
- The sidebar `pl*` helpers (lines 1–30 of `pipeline.js`) and the Pipeline card —
  these become the visible live status tracker.
- All `handle()` dashboard rendering.

### Added
1. **Skeleton placeholders.** `dashSkeleton()` injects shimmer rows into
   `#clusters` on run start; the first real `renderClusters` clears them. Graph
   hint copy switches to a live "building…" message on start.
2. **Typed-label effect.** `typeText(node, text)` types a string in
   char-by-char (instant under reduced-motion). `renderClusters(cs, {typed})`
   types only labels not seen this run (tracked in a module `_shownLabels` set,
   reset on run start); existing labels render instantly. New cluster cards get a
   `dash-rise` entrance animation; existing cards don't.
3. **Panel reveal.** A `reveal` CSS class (fade+rise) added to the voices and
   evidence panels when they first populate.

### Event → live UI mapping (all already in `handle()` unless noted)

| event | live effect |
|---|---|
| `started` | sidebar Pipeline → seed active; `dashSkeleton()` shows; reset `_shownLabels` |
| `seeded` / `iter_start` | Pipeline → fetch active + meta |
| `posts_fetched` | `#m-posts` climbs; Pipeline fetch meta |
| `clustered` | `#m-clusters`, `#m-entropy` set; Pipeline cluster active |
| `labeled` | `renderClusters(clusters, {typed:true})` → new labels type in + cards rise; `renderSentChart` |
| `reranked` | `renderClusters(clusters)` instant update; `renderSentChart` |
| `evidence_ready` | fetch + `renderEvidence` → evidence panel `reveal` |
| `briefing_ready` | briefing link shown; Pipeline brief done |
| `done` | `drawGraph` renders the topic graph; voices `reveal` if present |
| errors | Pipeline stage marked; dashboard keeps whatever it has |

### Data flow (unchanged backbone)

```
SSE /events ─▶ agent.js subscribe ─▶ handle(ev) ─▶ live dashboard renderers
                                                    (KPIs, charts, typed clusters, graph)
```

No new endpoints, no event-schema changes, no overlay.

## Files

- `static/js/pipeline.js` — delete the `PL2` IIFE (keep sidebar `pl*` helpers).
- `static/js/agent.js` — drop `PL2.start()`/`PL2.event(ev)`; on run start call
  `dashSkeleton()` + `resetTypedLabels()`; pass `{typed:true}` to
  `renderClusters` on `labeled`.
- `static/js/clusters.js` — add `typeText`, `_shownLabels`/`resetTypedLabels`,
  `dashSkeleton`; extend `renderClusters(cs, opts)` for typed + rise + skeleton
  clear; add `reveal` to voices.
- `static/js/evidence.js` — add `reveal` to the evidence panel on render.
- `static/css/animations.css` — skeleton shimmer, typed caret, `dash-rise`,
  `reveal` styles. (Old dead `pl2-*` overlay rules left in place; out of scope.)
- `templates/partials/_loader.html` — empty the `#pl2` overlay markup.

## Error handling

- Connector/embed/briefing errors mark the sidebar Pipeline stage (existing
  `handle()` behavior) and leave whatever the dashboard already built intact.
- SSE drop (`es.onerror`) keeps existing behavior (`#go` re-enabled).

## Testing

Repo has only a pytest harness (no JS runner). `typeText` and the
`renderClusters` typed/skeleton logic are DOM-touching, so verification is
`node --check` (syntax) + a manual run on the droplet watching the dashboard
build live against the docker event log. Limitation acknowledged, not papered
over.

## Risks

- Re-render churn: `renderClusters` rebuilds the whole list on both `labeled` and
  `reranked`. The `_shownLabels` set prevents re-typing / re-animating existing
  labels, so only genuinely new ones animate. Reset per run.
- Empty gap before first data → skeletons cover it; KPIs at 0 and Pipeline
  "working…" make it clear work is underway.
