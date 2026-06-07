# Opinion-Aware Evidence Dashboard — Design

> Status: design approved, pre-implementation. Branch: `feat/opinion`.
> Date: 2026-06-07. Spec input: task brief (Opinion-Aware Evidence Dashboard).

## Goal

Redesign the dashboard for evidence-based decision making. User optionally
provides a personal opinion / hypothesis / intended decision. When present, the
system investigates the topic from multiple perspectives and presents balanced
evidence both supporting and opposing the opinion. When absent, neutral analysis.

Inspiration: Ground News (compare framings) + X Community Notes (competing
claims with evidence). "Community Notes for Anything."

## Approved decisions

1. **Investigation depth** — when opinion set, agent biases seed + expansion
   queries toward *both* supporting and challenging angles (active counter-
   evidence seeking), then analyzes. Neutral query path when no opinion.
2. **Analysis layer** — new post-processing module producing `evidence.json`
   from a completed run. Agent stays mostly unchanged; layer reusable by
   dashboard and briefing.
3. **Frontend** — extend existing `templates/index.html` SPA with opinion input
   + tabbed result views. No new route, no build step.
4. **Scoring** — hybrid: deterministic signals computed in Python (testable) +
   LLM plausibility judgment, blended into one confidence score.

## Data flow

```
topic + optional opinion
   -> POST /run            (request now carries `opinion`)
   -> agent loop           (opinion -> pro/con-biased seed + expansion queries)
   -> clusters.json + posts.json     (existing shape, unchanged)
   -> lib/evidence.py:build(run_id, opinion) -> evidence.json   [NEW]
   -> SSE "evidence_ready"
   -> dashboard GET /run/<run_id>/evidence
```

Existing briefing HTML/PDF and SSE pipeline untouched.

## `evidence.json` structure

Maps to the 8 required output sections.

```jsonc
{
  "opinion": "I want to play Elden Ring ...",   // null when neutral
  "exec_summary": {
    "plain_topic": "...",          // topic in plain language
    "key_findings": ["..."],
    "agreements": ["..."],         // major areas of agreement
    "disagreements": ["..."],      // major areas of disagreement
    "conclusion": "..."            // high-level, takes no position
  },
  "topic_overview": "...",
  "community_consensus": {
    "top_praise": ["..."],
    "top_criticism": ["..."],
    "misconceptions": ["..."],     // frequently repeated, likely false
    "uncertainties": ["..."]
  },
  "claims": [
    {
      "text": "...",
      "side": "pro" | "con" | "neutral",
      "confidence": 0.0,           // blended 0-1
      "evidence_strength": "weak" | "moderate" | "strong",
      "reasoning": "brief why",
      "source_categories": ["reviews","forums","social","expert"],
      "cluster_ids": [int],
      "ranking": {                 // 5-axis, 0-1 each
        "credibility": 0.0,
        "data_quality": 0.0,
        "sample_size": 0.0,
        "recency": 0.0,
        "corroboration": 0.0
      }
    }
  ],
  "screen_a": [claim, ...],        // side == pro   (only when opinion set)
  "screen_b": [claim, ...],        // side == con   (only when opinion set)
  "uncertainty": ["..."],          // areas of missing information
  "final_assessment": "..."        // balanced; avoids false balance
}
```

When no opinion: `screen_a` / `screen_b` empty, claims tagged `neutral`,
dashboard shows a single Neutral Analysis view.

## Modules

Respect ~200-line cap and one-responsibility rule.

### `lib/evidence_score.py` (pure, TDD)
Pure functions over a cluster + its posts. No IO, no LLM.
- `sample_size(cluster)` -> member count.
- `engagement(cluster, posts_by_id)` -> summed likes/comments.
- `source_diversity(cluster, posts_by_id)` -> distinct source count.
- `recency(cluster, posts_by_id, now)` -> newest-post recency score.
- `corroboration(cluster, posts_by_id)` -> #independent sources agreeing.
- `rank(cluster, posts_by_id, now)` -> 5-axis `ranking` dict (normalized 0-1).
- `strength_bucket(ranking)` -> "weak"|"moderate"|"strong".
- `blend(computed_norm, llm_conf)` -> final confidence 0-1.
Empty inputs return zeros, not errors (per rules).

### `lib/evidence.py` (orchestration)
- `build(run_id, opinion: str | None) -> dict` — loads run + clusters + posts,
  calls LLM via `lib/llm.py:chat_json` for claim extraction + plausibility +
  summary + consensus + assessment, merges with `evidence_score` ranking,
  writes `evidence.json`, returns it.
- LLM prompts: claims (pro/con/neutral split, source categories, reasoning,
  llm confidence), exec summary, community consensus, final assessment.
- All structured LLM output strict-JSON via `chat_json` + retry (per rules).
- Behavior rules baked into prompts: never optimize for agreement; seek
  strongest evidence both sides; distinguish fact/interpretation/opinion;
  flag uncertainty + missing info; avoid false balance when evidence is
  lopsided; prefer evidence over popularity.

### `lib/agent.py` (edit)
- `run_agent(topic, sources, run_id=None, opinion=None)`.
- When `opinion` set: seed + next-query system prompts ask for queries probing
  both supporting and challenging angles of the opinion. Neutral prompts else.
- After loop: call `evidence.build(run_id, opinion)`, publish `evidence_ready`.

### `server.py` (edit)
- `/run` accepts `opinion` (optional string), passes to `run_agent`.
- New `GET /run/<run_id>/evidence` -> serves `evidence.json` (404 if absent).

### `templates/index.html` (edit)
- Add optional **"My Opinion"** textarea beside topic input.
- Result tabs: `Summary · Overview · Consensus · Evidence ·
  Why-Right (A) · Why-Wrong (B) · Uncertainty · Assessment`.
  A/B hidden when no opinion -> single Neutral Analysis tab.
- Per-claim cards show confidence score, evidence-strength badge, brief
  reasoning, source-category chips.
- Chart.js (CDN, already present) visualizations, render only when data exists:
  sentiment distribution, pro-vs-con bar, confidence-by-claim, criticism
  frequency. Selection driven by available data.

## Output section -> source mapping

| # | Section                       | Source field |
|---|-------------------------------|--------------|
| 1 | Executive Summary             | `exec_summary` |
| 2 | Topic Overview                | `topic_overview` |
| 3 | Community Consensus           | `community_consensus` |
| 4 | Evidence Visualizations       | charts over `claims` + cluster sentiment |
| 5 | Why This Opinion May Be Correct | `screen_a` |
| 6 | Why This Opinion May Be Wrong   | `screen_b` |
| 7 | Key Areas of Uncertainty      | `uncertainty` |
| 8 | Final Balanced Assessment     | `final_assessment` |

## Tests

- `tests/test_evidence_score.py` — pure scoring math; write first (TDD).
  Cases: empty cluster -> zeros; sample/engagement/diversity/recency/
  corroboration monotonicity; `blend` bounds; `strength_bucket` thresholds.
- `tests/test_evidence.py` — `build()` with mocked `chat_json` + fixture
  clusters/posts; asserts evidence.json shape, screen_a/b split, neutral path.
- `tests/test_agent_opinion.py` — opinion-biased seed queries (mock LLM);
  asserts neutral prompt when opinion absent, dual-angle prompt when present.

## Behavior rules (enforced in prompts + assessment)

Never optimize for agreement. Seek strongest evidence for and against.
Distinguish facts / interpretations / opinions. Explicitly identify uncertainty
and missing information. Avoid false balance when evidence overwhelmingly favors
one side. Present competing perspectives fairly. Prefer evidence over popularity.

## Out of scope

Auth, durable DB, new deployment. Reuse existing connectors, embeddings,
clustering, stance, briefing, SSE bus.
