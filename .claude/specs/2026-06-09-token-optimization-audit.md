# Token Optimization Audit + Improvements

> Date: 2026-06-09. Branch `feat/prompting` (off `shyan`).
> Method: executable code is the source of truth. Comments and docs were not
> trusted — every claim verified against the runtime path in `lib/`.
> **Legend:** ✅ implemented (runtime path exists) · ⚠️ partial · ❌ absent

## Scope note
Token-optimization touches the LLM/embedding paths only: `lib/embed.py`,
`lib/llm.py`, `lib/backend.py`, `lib/agent.py`. `lib/mcp/` and
`lib/orchestration/` are empty on `shyan` (they live on other branches) and are
not token-optimization code, so they are out of scope for this audit.

---

## Audit findings

### Q-token-01 — Gemini Context Caching — ❌ ABSENT
- Persistent context reuse: none.
- Snapshot restoration: none.
- Cross-request cache: none.
- Context reconstruction: none.

Evidence: every chat goes through `lib/llm.py:chat_json` →
`_chat_openai_compat`, which calls `client.chat.completions.create(...)` against
Gemini's **OpenAI-compatible** endpoint (`backend.py:37`). No `cached_content`
parameter, no `genai.CachedContent`, no cache handle is created, stored, or
reused. `grep -rniE "cached_content|CachedContent|context cach"` over `lib/`,
`server.py`, `main.py` returns nothing. Mark **absent** per status rule (no
runtime execution path). Note: Gemini *implicit* caching may trigger
server-side for large 2.5 prompts, but that is provider behavior, not code in
this repo, and our system prompts are short.

### Q-token-02 — Rolling Summary Memory — ❌ ABSENT
- Context summarization: none.
- Memory compaction: none.
- Summary regeneration: none.
- Historical injection: none.

Evidence: the agent loop (`lib/agent.py:run_agent`) carries state across
iterations as structured data (`seen` posts, `cluster_meta`, `prev_cents`), not
as a growing LLM transcript. The only history fed back into an LLM call is the
list of **cluster labels** passed to `_llm_next` (`agent.py:307`) — a compact
state hand-off, not a generated/regenerated running summary. No summary is
produced and reused. Mark **absent** per status rule.

### Q-token-03 — Prompt Caching — ❌ ABSENT (not explicit)
- Static prompt reuse: system prompts are module-level constants
  (`_SEED_NEUTRAL`, `_SEED_OPINION` in `agent.py`), so the *strings* are reused,
  but…
- Prompt deduplication: none across calls.
- Prefix caching: none — no `cache_control` block, no provider cache directive.
- Persistent system prompt handling: each `chat_json` call rebuilds
  `messages=[{system},{user}]` fresh (`llm.py:42-45`).

Verdict: documentation-level only. The prior audit (`nice.md:81`) already flagged
this as "LLM prompt-cache not explicit ⚠️" — confirmed: **no real
implementation**. Implementing genuine prefix/prompt caching would be
provider-specific (Anthropic `cache_control` vs Gemini `cached_content`),
unverifiable here without live keys, and a broad change — out of scope per the
"avoid broad refactors / keep changes measurable" rules. Left absent and
documented honestly rather than faked.

### Q-token-04 — Embedding Cache (`data/embed_cache.jsonl`) — ✅ IMPLEMENTED
- SHA1 cache key: ✅ `_key()` → `sha1(f"{backend_tag}::{text}")` (`embed.py`).
  Keyed by backend tag (`provider:model`) so a model switch is a natural
  invalidation — old keys simply never match.
- Read path: ✅ `_load_cached()`.
- Write path: ✅ `_append_cache()` (append-only JSONL).
- Cache-hit execution: ✅ only cache-miss keys are sent to the provider.
- Serialization: ✅ one JSON object per line, `{"k": <sha1>, "v": [floats]}`.
- Invalidation: ✅ by backend-tag in the key. ⚠️ no size cap / eviction — the
  live file had grown to **335 MB / 5074 entries**.
- Token-reduction impact: ✅ a hit skips the embedding API call entirely.

This was the **only real optimization layer present** — and it had a measurable
performance bug (below).

---

## Optimization gaps found
1. **`_load_cache()` slurped the entire 335 MB file into a dict on _every_
   `embed_texts()` call**, json-parsing ~60 KB float vectors per line even
   though a call needs only the handful of keys in its own batch. The agent
   calls `embed_texts` once per iteration (up to `MAX_ITERS=4`), so the whole
   cache was re-parsed several times per run.
2. **Identical texts in one batch were embedded more than once.** Duplicates
   share a key but both landed in `missing_idx`, costing redundant embedding
   tokens and appending duplicate rows. (The docs even claimed "identical text
   skipped" — which was false.)

## Implementation (changes made)
Narrow, backward-compatible, same on-disk format.

- `lib/embed.py`
  - `_load_cache()` → **`_load_cached(wanted: set[str])`**: scans the file but
    only materializes the keys this batch needs, and **early-exits** once all
    wanted keys are found. Added `_peek_key()` — a regex that pulls the sha1 out
    of the first 64 chars of a line so non-wanted rows are skipped *without*
    json-parsing their 60 KB vector.
  - `embed_texts()` now **de-duplicates missing keys** before calling the
    provider: identical strings are embedded once, written once.
- `lib/docs_content.py`: corrected two now-stale/false cache claims
  ("cached per run" → "cached across runs (sha1-keyed JSONL)"; "Per-run;
  identical text skipped" → "Cross-run sha1 JSONL; identical text
  de-duplicated per batch").
- `tests/test_embed.py`: +5 tests (peek-key format, targeted load, cache-hit
  skips provider, in-batch dedup).

## Validation evidence
- New + existing embed tests: **7 passed** (`pytest tests/test_embed.py`).
- Full suite: **300 passed, 11 skipped** (`--ignore=tests/test_facebook_connector.py`;
  that module fails to collect on `shyan` due to a pre-existing missing symbol
  `_parse_engagement`, unrelated to this change).
- Benchmark against the live 335 MB cache, looking up a 3-key batch:

  | | time | peak mem | entries held |
  |---|---|---|---|
  | old `_load_cache()` | 17 576 ms | 493 MB | 5071 (all) |
  | new `_load_cached()` | 453 ms | 0.1 MB | 3 (wanted) |
  | | **38.8× faster** | **~4268× less** | |

## Risks
- `_peek_key` assumes the writer emits `"k"` first (it does — `_append_cache`
  controls the format). If the format ever changes, the regex falls back to
  `None` and that row is skipped (treated as a miss) — degrades to a re-embed,
  never returns wrong data.
- Early-exit means a batch that is entirely new (all misses) still reads the
  whole file — unchanged worst case, no regression.
- No behavior change to embeddings returned; pure read-path + dedup.

## Future improvements (not done here — would need broader work)
- Embedding cache eviction / size cap, or a sidecar key index to avoid the
  full-file scan on cold misses.
- Real prompt/prefix caching once a provider that supports it is the runtime
  default (Q-token-03).
- Rolling-summary memory only if the agent ever feeds long transcripts to the
  LLM (Q-token-02) — currently it does not, so there is nothing to compact.
