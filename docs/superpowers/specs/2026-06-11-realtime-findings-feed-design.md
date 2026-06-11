# Real-Time Findings Feed — Design

> Status: approved (design). Branch: `feat/realtime`.
> Date: 2026-06-11

## Problem

A run currently shows a full-screen loader animation (`PL2`, `static/js/pipeline.js`)
for its entire duration (~2–6 min), then reveals the whole dashboard at once when
the `done` event fires. The wait feels opaque and frustrating — the user gets no
sense of progress or what is being found.

Crucially, the dashboard **already builds progressively** in `static/js/agent.js`
`handle()`: `posts_fetched` bumps the count, `clustered` updates k/entropy,
`labeled` calls `renderClusters()` + `renderSentChart()` every iteration,
`reranked` re-renders with real sentiment. That live build is simply **hidden
behind the `PL2` overlay**, which covers the screen until `done`.

A second issue: `PL2` fakes progress with a **simulated stage timer**
(`startSim` / `APPROX` advancing stages on a clock), which is decoupled from real
work — the source of the earlier "count stuck at 0" and "badge overlaps later
stages" bugs.

## Goal

Replace the fake stage animation with a **real-time, event-driven findings feed**:
a narrative, chat-like stream of discrete findings as they actually happen. At
`done`, the feed fades out and the full interactive dashboard takes over (clean
handoff — feed gone).

Non-goals: changing the backend agent loop, the SSE event schema, or the
dashboard rendering in `agent.js`. This is a presentation-layer change to the
loader only.

## UX

```
DURING (overlay):                 AT DONE:
  Analyzing "life of pi"…           ┌─ dashboard ───────┐
  ──────────────────────            │ charts   graph    │
  ✓ 6 search angles                 │ clusters voices   │
  ✓ 115 posts found · reddit 80…    │ briefing          │
  ✓ grouped into 7 themes           └───────────────────┘
  ✓ Theme: Life of Pi meanings (39) (feed faded out)
  ✓ Theme: VFX industry (6)
  ⟳ expanding queries…
  ✓ 65 more posts
  ✓ Sentiment: 49% negative
  → Building your dashboard…
```

- Each finding appears with a fade/slide-in.
- The newest in-progress line carries a spinner; once the next finding arrives,
  the prior line resolves to a ✓.
- The feed auto-scrolls to the latest line.
- Error events render a red line but still let the (partial) dashboard reveal.

## Architecture

Presentation-only; lives inside the existing `#pl2` overlay shell.

### Components

1. **`feedLineFor(ev, state)` — pure mapper.**
   Input: one SSE event object + a mutable `state`. Output: array of 0+ line
   descriptors `{ icon, text, kind }` (`kind` ∈ `info | progress | good | warn |
   err | final`). No DOM access — unit-reasonable in isolation.
   `state` holds:
   - `seenLabels: Set<string>` — so `labeled` emits only *new* themes.
   - `plats: {source: count}` — running per-source tallies for the posts line.
   - `iter: number` — current iteration.

2. **Feed renderer.**
   `pushLine(desc)` appends a node to the feed container with fade-in, resolves
   the previous `progress` line to ✓, applies a spinner to the new `progress`
   line, and auto-scrolls. Owns no business logic.

3. **Lifecycle (`PL2` public API).**
   - `start(topic)` — open overlay, reset state, render header `Analyzing
     "topic"…`, clear feed.
   - `event(ev)` — `feedLineFor(ev, state).forEach(pushLine)`.
   - internal `complete()` — on `done`: push `→ Building your dashboard…`, then
     fade the overlay out (CSS) and remove `.open`. Dashboard underneath is
     already rendered by `agent.js`.

### Event → line mapping

| event | line(s) |
|---|---|
| `seeded` | `✓ {n} search angles` |
| `iter_start` (iter > 1) | `⟳ expanding queries…` (progress) |
| `posts_fetched` | `✓ {n_total} posts found · {src tallies}` (uses `state.plats`) |
| `low_recall` | `… thin results, broadening search` (warn) |
| `clustered` | `✓ grouped into {k} themes` |
| `labeled` | one `✓ Theme: {label} ({n})` per label not in `seenLabels` |
| `reranked` | `✓ Sentiment: {neg}% negative · {pos}% positive` (avg over clusters) |
| `briefing_ready` | `✓ Briefing ready` |
| `evidence_ready` | `✓ Evidence compiled` |
| `embed_error` / `briefing_error` / `error` | red line; do not block reveal |
| `done` | `→ Building your dashboard…` (final) → fade |

Sentiment % for `reranked`: average each cluster's `sentiment.{pos,neg}`
weighted by cluster `n`, ×100, rounded.

### Data flow

```
SSE /events ─▶ agent.js subscribe ─▶ handle(ev) ─┬─▶ (existing) dashboard render
                                                  └─▶ PL2.event(ev) ─▶ feedLineFor ─▶ pushLine
```

Unchanged: `agent.js` continues rendering the dashboard underneath. No new
endpoints, no event-schema changes.

### Removed

`startSim`, `APPROX`, `setStage`, `setMin`, `renderAnim`, the stage rail
(`buildRail`/`paintRail`), `paintCount` + the `pl2-livecount` badge, the
reassure/eta timers tied to the stage sim. The earlier count-race and
badge-overlap bugs disappear with them.

## Files

- `static/js/pipeline.js` — rewrite: overlay shell + feed renderer + mapper.
- `static/css/animations.css` — feed line styles (fade-in, spinner, icon colors).
- `templates/partials/_loader.html` — slim shell: header + scrollable feed body.
- `static/js/agent.js` — pass `topic` to `PL2.start(topic)` in `start()`.

## Error handling

- Connector/embedding/briefing errors → a red `warn`/`err` feed line; the run may
  still emit `done` (graceful backend), which reveals whatever the dashboard has.
- If SSE drops (`es.onerror` in `agent.js`), existing behavior stays: the feed
  stops, overlay can be dismissed; no change required here.

## Testing

Repo has only a pytest harness (no JS runner). `feedLineFor` is kept pure so it
*could* be unit-tested under node, but we will not fake a pytest for it. Verify
via `node --check` (syntax) + a manual run on the droplet watching the feed
against the docker event log. This limitation is acknowledged, not papered over.

## Risks

- `reranked`/`labeled` cluster shapes must match what `agent.js` already
  consumes (they do — same events). Mapper reads the same fields.
- Auto-scroll + many themes: cap nothing; runs emit ~5–8 themes/iter, feed length
  is bounded and scrollable.
