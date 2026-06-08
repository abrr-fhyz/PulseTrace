# last30days vs PulseTrace — search-quality benchmark + techniques copied

Head-to-head benchmark of PulseTrace's agent against the `last30days` engine
(vendored at `last30days-skill/`), plus the retrieval techniques we ported from
it. Harness: `eval/compare_agents.py`. Branch where the work landed:
`feat/improved_agent`.

## How the benchmark works

Both systems run on **identical topics** (3), **identical cheap sources**
(reddit + hackernews — the keyless overlap), and the **same Gemini brain**. A
pooled Gemini judge grades the union of both ranked lists 0–3; each system is
scored against those shared grades (mirrors last30days' own judged-pool eval).
This isolates *agent/ranking quality* from API-key access.

- PulseTrace ranked list = clusters' `top_posts` (round-robin across clusters).
- last30days ranked list = `ranked_candidates` from `--emit=json --quick`.
- Metrics: Precision@5, nDCG@5, mean grade, source diversity, latency, URL Jaccard.

## Results ladder (PulseTrace nDCG@5)

| stage | nDCG@5 | precision@5 | mean grade | latency |
|---|---|---|---|---|
| baseline (engagement-only `top_n`) | 0.117 | 0.13 | 0.54 | 49s |
| + relevance gate + relevance rank | 0.197 | 0.13 | 0.92 | 35s |
| + LLM rerank (gemini-2.5-flash-lite) | 0.441 | 0.47 | 1.29 | 65s |
| + match their model (gemini-3.1-flash-lite) | **0.716** | **0.53** | **1.58** | 57s |
| last30days (gemini-3.1-flash-lite) | 0.520 | 0.467 | 1.375 | 22s |

**Verdict:** after the rerank work + model parity, PulseTrace reaches
parity-to-slightly-ahead on *relevance quality*, but is ~2.5× slower.

## Honest caveats (don't over-claim the win)

- **n=3 topics.** Small. Directional, not a labeled benchmark.
- **last30days is noisy run-to-run.** Its reddit+hn fetch flaked on the
  headphones topic (nDCG 0.83 → 0.0 → 0.0 across runs), inflating our aggregate
  win. On the one topic where both got full data (RAG) it was a tie (1.0/1.0).
  On Codex pricing last30days still beat us (0.56 vs 0.29).
- **Latency gap is real and ours.** LLM rerank runs every agent iteration
  (multiple `reranked n=30` calls/run). last30days reranks once.
- **The judge model is the same for both** within a run (fair grader), but it
  changed between rungs (2.5 → 3.1), so cross-rung deltas are slightly
  confounded. The PT-vs-l30d comparison *within* each run is clean.

## Root cause of the original 6× gap

PulseTrace ranked `top_posts` by **engagement only** (`influence.top_n`):
`log1p(reactions) + 2·log1p(comments) + 3·log1p(shares) + 0.5·recency`. No
relevance term anywhere. A viral "Roast my resume" post beat an on-topic RAG
explainer. Query expansion also drifted (RAG → "RAG for resume parsing" →
recruitment), polluting the corpus so even good clustering surfaced junk.

## Techniques copied (now in PulseTrace)

1. **Query-centric relevance scoring** — `lib/relevance.py:token_overlap_relevance`.
   Coverage + informative-token coverage (down-weights low-signal words like
   `best`/`review`/`odds`/`pricing`) + precision penalty + phrase bonus. Caps
   generic-only matches below the filter line. Source: `last30days .../lib/relevance.py`.
2. **Core-subject extraction** — `lib/relevance.py:extract_core_subject`. Strips
   "what are the best…/how to…" prefixes + noise words. Source: `lib/query.py`.
3. **Relevance-dominant score blend** — `lib/rerank.py:final_score`:
   `0.60·relevance + 0.20·engagement + 0.15·recency + 0.05·source_quality`,
   ×0.3 hard demotion below the relevance floor. Source: `lib/rerank.py:_final_score`.
4. **Intent-aware LLM rerank** — `lib/rerank.py:llm_rerank`. 0–100 relevance
   scoring, demote <20, deterministic token-overlap fallback, prompt-injection
   fencing of untrusted content. This was the single biggest lever.
5. **Relevance gate before clustering** + **anchored query expansion** in
   `lib/agent.py` (kills corpus pollution and topic drift).

## Techniques NOT yet copied (next wins)

- **Match the model by default.** last30days uses `gemini-3.1-flash-lite`
  everywhere; we default to `gemini-2.5-flash-lite`. The 2.5→3.1 bump alone
  moved nDCG 0.441 → 0.716. Consider defaulting our chat model to 3.1-flash-lite
  (or a per-stage override so only rerank/judge use the stronger model).
  `chat_json` currently uses one model for all stages (`GEMINI_CHAT_MODEL`);
  add per-stage model selection to do this cheaply.
- **30-day date window.** last30days restricts fetches to the last 30 days
  (`lib/dates.py`); PulseTrace fetches all-time, so stale posts pollute results.
- **Weighted RRF cross-source fusion** + **URL-normalized dedup** +
  **per-author/diversity caps** — `last30days .../lib/fusion.py`.
- **Web-search connector** (brave/exa/serper) — `last30days .../lib/grounding.py`.
  We have `SERPERDEV_API_KEY` in `.env` but no web connector at all. This is a
  whole source class last30days has and we lack.
- **Rerank once, not per-iteration** — to close the latency gap.

## Repro

```bash
.venv/bin/python eval/compare_agents.py                      # 3 default topics, our model
GEMINI_CHAT_MODEL=gemini-3.1-flash-lite \
  .venv/bin/python eval/compare_agents.py                    # model-parity run
```
Needs `gemini_paid_api_key` in `.env.api_keys`; `uv` for the last30days side.
Related: [[models]].
