# Hybrid + Self-Reflective RAG — Design

Date: 2026-06-09
Branch: `refactor/hybrid_RAG`
Status: approved, pending implementation plan

## Goal
Close the RAG gap flagged in `.claude/submission-gap-audit.md`. Current
`lib/rag.py:ask()` does pure dense FAISS top-k → LLM. The submission form claims
**hybrid search (BM25 + dense, RRF fusion)** and a **self-reflective layer**
(confidence check → refined re-retrieval, capped at 2 iterations). Build both so
the claim is true.

## Scope (approved)
- Hybrid retrieval: BM25 + dense FAISS, merged via Reciprocal Rank Fusion.
- Self-reflective loop: LLM-as-judge confidence → query refine → re-retrieve, ≤2 iters.
- New dep: `rank_bm25>=0.2`.
- Replace internals of `ask()`, keep its signature (callers untouched).

Out of scope (YAGNI): persisted BM25 index, Cohere/BGE rerankers, pgvector,
session-scoped SQL retrieval, sentence-transformer swap.

## Architecture
```
lib/retrieve.py   NEW   hybrid retrieval: dense (FAISS) + BM25 (rank_bm25) → RRF merge
lib/rag.py        EDIT  orchestrate: retrieve → answer → judge → re-retrieve(≤2) → finalize
requirements.txt  EDIT  + rank_bm25>=0.2
tests/test_retrieve.py  NEW
tests/test_rag.py       NEW/EXTEND
```

File split rationale: retrieval is a distinct responsibility with its own pure
RRF math worth isolating + testing; keeps both files under the ~200-line soft cap.

### Module: `lib/retrieve.py`
Responsibility: given a run_id + query string, return a ranked list of post ids.

Functions:
- `_tokenize(text: str) -> list[str]` — lowercase, split on non-alphanumeric. Pure.
- `rrf_merge(rankings: list[list[str]], k: int = 60) -> list[str]` — Reciprocal
  Rank Fusion over multiple ranked id lists. `score(id) = Σ 1/(k + rank)` where
  rank is 0-based position in each list the id appears in. Returns ids sorted by
  descending fused score. Pure — fully unit-testable, no IO.
- `dense_search(run_id, query, n) -> list[str]` — embed query, FAISS top-n ids.
  Reuses existing `index.faiss` + `ids.json`. (Lifted from current `rag.ask`.)
- `bm25_search(posts, query, n) -> list[str]` — build `BM25Okapi` in-memory from
  tokenized post texts, return top-n post ids. Corpus ≤ MAX_POSTS=500 → cheap.
- `hybrid_search(run_id, query, k, n=20) -> list[str]` — run dense_search + bm25_search
  (pool of `n` each), `rrf_merge`, return top-`k` ids. If `rank_bm25` import fails
  OR bm25 yields nothing → fall back to dense-only (log + continue).

Import of `rank_bm25` is the one allowed deferred/optional import (heavy optional
dep exception in coding-standards) so a missing lib degrades instead of crashing
module load.

### Module: `lib/rag.py` (edited)
`build_index`, `_normalize_cite`, `_resolve_shot_url`, `_citation_detail`,
`ASK_SYS` — unchanged.

New constants: `REFLECT_THRESHOLD = 0.6`, `MAX_REFLECT_ITERS = 2`.

New `JUDGE_SYS` prompt — strict JSON:
`{"confidence": 0.0-1.0, "supported": bool, "gap": "what's missing or unsupported"}`
Evaluates the drafted answer against the retrieved posts only.

New `REFINE_SYS` prompt — strict JSON: `{"query": "rewritten search query"}` given
original question + judge gap note.

Rewritten `ask(run_id, question, k=8) -> dict`:
1. Ensure index (existing build_index guard). Empty → existing "No data" return.
2. Load posts dict once.
3. Loop, `iters` from 1 to `MAX_REFLECT_ITERS`:
   a. `hits = hybrid_search(run_id, query, k)` (query = question on iter 1).
   b. Build context (existing format), `out = chat_json(ASK_SYS, ...)`.
   c. `judge = chat_json(JUDGE_SYS, ...)`; on exception → break with current answer,
      confidence treated as 1.0 (skip reflection).
   d. Keep best answer by confidence.
   e. If `confidence >= REFLECT_THRESHOLD` or `iters == MAX_REFLECT_ITERS` → stop.
   f. Else `query = chat_json(REFINE_SYS, gap)["query"]`; on exception → stop.
4. Return best answer's `{answer, citations, citations_detail, retrieved}` plus
   `confidence` and `iterations`.

## Data flow
```
question
  └─► iter ≤ 2:
        hybrid_search(query) ──► context ──► chat_json(ASK_SYS) ──► answer
        answer + context ──► chat_json(JUDGE_SYS) ──► {confidence, gap}
        confidence < 0.6 and iters < 2 ?
            yes ──► chat_json(REFINE_SYS, gap) ──► new query ──► loop
            no  ──► finalize best
  └─► {answer, citations, citations_detail, retrieved, confidence, iterations}
```

## Error handling (degrade, never crash — coding-standards)
| Failure | Behavior |
|---|---|
| `rank_bm25` import fails | `hybrid_search` → dense-only |
| bm25 returns empty | dense-only for that call |
| empty corpus / no index | existing `{"answer": "No data..."}` |
| `ASK_SYS` LLM throws | existing `{"answer": "LLM error: ..."}` early return |
| `JUDGE_SYS` LLM throws | skip reflection, return current answer (conf=1.0) |
| `REFINE_SYS` LLM throws | stop loop, return best so far |

## Testing (TDD — write tests first)
`tests/test_retrieve.py`:
- `rrf_merge` — known rankings → expected fused order (pure, no mocks).
- `rrf_merge` — id appearing in multiple lists scores higher than single-list id.
- `_tokenize` — punctuation/case handling.
- `bm25_search` — small corpus, query term → ranks matching post first (real rank_bm25).
- `hybrid_search` — monkeypatch `dense_search` + `bm25_search`, assert RRF order.
- `hybrid_search` — simulate `rank_bm25` unavailable → returns dense order (fallback).

`tests/test_rag.py`:
- `ask` — mock `chat_json`: answer then judge conf=0.9 → 1 iteration, no refine.
- `ask` — mock `chat_json`: judge conf=0.3 then refine then conf=0.9 → 2 iterations,
  refine called once, re-retrieval fired.
- `ask` — judge conf stays low both iters → stops at `MAX_REFLECT_ITERS`, returns best.
- `ask` — `JUDGE_SYS` raises → 1 iteration, answer returned, conf=1.0.
- Mock `embed_texts` + faiss read OR use a tiny built index fixture; mock `hybrid_search`
  where retrieval internals aren't under test.

All external IO (OpenAI/Gemini via `chat_json`, `embed_texts`) mocked per coding-standards.

## Config knobs
| Name | Default | Where |
|---|---|---|
| `RRF_K` | 60 | `lib/retrieve.py` |
| retriever pool `n` | 20 | `hybrid_search` arg |
| `REFLECT_THRESHOLD` | 0.6 | `lib/rag.py` |
| `MAX_REFLECT_ITERS` | 2 | `lib/rag.py` |

## After merge
Update `.claude/submission-gap-audit.md`: move hybrid search + RRF + self-reflective
RAG from ❌ to ✅. Update `.claude/memory/project-snapshot.md` RAG line.
