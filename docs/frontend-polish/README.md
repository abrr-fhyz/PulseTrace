# Frontend Polish Pass

Final UI/UX pass on the dashboard before merge into `shyan`. Covers panel
spacing, the color system, sentiment correctness, topic-graph animation, PDF
failure recovery, and theme-toggle cleanup.

## Screenshots

| | |
|---|---|
| Dashboard overview | `01-dashboard-overview.png` |
| Sentiment-by-cluster (fixed) | `02-sentiment-by-cluster-fixed.png` |
| Topic-graph spheres | `03-topic-graph-spheres.png` |
| PDF failure recovery | `04-pdf-failure-recovery.png` |

## Root-cause notes

### Sentiment-by-cluster showed 100% neutral (blocker)

**Root cause — event ordering, not data.** Stance/sentiment is computed *after*
the agent loop, in the finalize/rerank pass (`lib/agent.py`,
`cluster_sentiments(...)`). But the `labeled` SSE event is published *inside*
the loop, where the local `sentiments` dict is still empty, so every cluster is
serialized with the default placeholder `{pos: 0, neu: 1, neg: 0}` — i.e. 100%
neutral. The dashboard's summary views (`renderClusters` + `renderSentChart`)
bound to that stale `labeled` payload and never refreshed. The drill-down looked
correct because it fetches `/run/<id>/cluster/<cid>`, which reads the
`clusters.json` that *is* rewritten with real sentiment after the rerank.

**Fix.** The `reranked` event (emitted once real sentiment exists) now carries
the enriched cluster list, and the frontend re-renders the summary chart and
cluster list on that event. Data shape was never the problem, so no aggregation
math changed. Sentiment colors are semantic: green / gray / red.

### Topic-graph spheres were not rotating (critical)

**Root cause — no animation loop existed.** The graph only ran a one-time
`fcose` layout animation; once it settled, node positions were static. There was
never a continuous rotation/`requestAnimationFrame` loop, so "previous
implementation appears incomplete" was literally true.

**Fix.** Added `startGraphSpin()` / `stopGraphSpin()`: a `requestAnimationFrame`
loop that orbits node model-positions around their centroid (~1 revolution /
~125s — subtle). It pauses on hover and drag, rebuilds the orbit after a manual
drag, honors `prefers-reduced-motion`, and is torn down on graph
destroy/redraw. Nodes also gained a radial-gradient fill so they read as 3D
spheres.

## Other changes

- **Panel overlap:** the left column was a bare `<section>` whose `.panel`
  children had no vertical margin and no flex gap, so they butted together. Both
  columns are now `.col` flex containers with a consistent `24px` gap; ad-hoc
  inline margins were removed.
- **Color system:** dark surfaces still dominate. The broad brand accent moved
  from blue to lavender/violet (`--accent2`), a bronze tertiary accent
  (`--accent4`) was added for heading dividers, and operational green
  (`--accent`) is reserved for status (done steps, online, success). Hardcoded
  blue tints were repointed to the brand token.
- **Semantic colors:** the full-screen loader's *completed* step markers were
  using the brand color; they now use operational green, matching the inline
  pipeline. Sentiment everywhere is green / gray / red.
- **PDF failure recovery:** a `briefing_error` previously routed to the generic
  "Something went wrong" screen, implying total failure even though all data and
  insights are already collected by that point. It now shows a dedicated
  "Your insights are ready" recovery screen with a success checklist and a large
  "View your dashboard →" button.
- **Theme toggle:** the toggle was vestigial — `toggleTheme()` was never defined
  (clicking threw a `ReferenceError`) and nothing ever wrote the stored
  preference. Removed the control and locked the app to its dark theme.
