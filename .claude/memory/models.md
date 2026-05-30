# Model Selection — Production E2E

> Decided 2026-05-30. Verified live against the paid Gemini API (key prefix `AQ.Ab8R…`). Used by `lib/backend.py` defaults and `.env.production.example`.

## Chat / Vision: `gemini-2.5-flash`

- **Why this one:** stable (not preview), 1M-token input context, 65K output, multimodal (text + image in one model so the Vision OCR path and the chat path use the same SKU). Replaces the deprecated `gemini-2.0-flash` which now returns `NOT_FOUND` for new users.
- **Cost (Dec 2025 paid pricing):** ~$0.30 / 1M input tokens, ~$2.50 / 1M output tokens. Roughly 5–10× cheaper than `gemini-2.5-pro` for materially similar quality on label/stance/RAG.
- **Trade-off vs `gemini-2.5-flash-lite`:** lite is ~3× cheaper but visibly weaker at multi-fact JSON output (cluster labels, stance reasoning). We keep `-lite` as the high-volume secondary for label/stance batches when the run is cost-bound, and `flash` for vision OCR + RAG answer generation.
- **Trade-off vs `gemini-3.5-flash` / `gemini-3.x-*-preview`:** newer, but `preview` channel can change schema mid-run. Stable channel is the prod choice; revisit when 3.x goes GA.

## Embedding: `gemini-embedding-2`

- **Why this one:** newest stable Gemini embedding model. 3072-dim output (same as `-001`, so on-disk vector cache is dimension-compatible). Improved retrieval quality on multi-lingual + opinion-mining benchmarks per Google's release notes.
- **Why not `gemini-embedding-2-preview`:** preview tier — schema not pinned, no SLA. Skip until promoted.
- **Why not `gemini-embedding-001`:** still works, but `-2` is the recommended upgrade path for new code. We keep `-001` as a hard-coded fallback inside `_embed_with_cascade` in case `-2` returns 503 on a hot rollout.
- **Dimension note:** `lib/backend.py:embed_dim` was 768 (legacy default for `text-embedding-004`). Bumped to 3072 to match the real Gemini output shape. Only affects empty-input zero-array shape; real embeds were already correct via `len(response.values)`.

## Fallback cascade (unchanged)

`lib/dispatch.py` still rotates every stage across all free providers (groq → openrouter → llm7 → huggingface → gemini → pollen → ollama) per `cascade_for_stage`. Gemini is now position-0 for paid-key users via `PULSETRACE_BACKEND=gemini`, but the cascade is preserved so a Gemini outage degrades to free providers instead of failing the run.

## Pricing math for typical run

- Topic: "Donald Trump Buffalo", 50 posts across 4 iters, 1 vision OCR per screenshot, 1 RAG turn with 4 questions.
- Estimated paid Gemini cost per run: ~$0.01–0.03 (mostly cached input).
- 10–50 runs ≈ $0.10–$1.50 total. Negligible vs free-tier rate-limit pain.

## Vision OCR config

- `tests/stages/test_18_fb_ocr_e2e.py` and `lib/catalogue.py` use the same model list: `[gemini-2.5-flash, gemini-2.5-flash-lite]`. The lite acts as a per-request fallback if flash 429s. Free-tier 15-RPM throttle is no longer the binding constraint with the paid key, but we keep the `time.sleep(4)` between OCR calls as a courtesy / safety net.

## Updating this doc

If you swap models, update:
1. `lib/backend.py:PROVIDERS["gemini"]` defaults
2. `.env.production.example:GEMINI_CHAT_MODEL` / `GEMINI_EMBED_MODEL`
3. `tests/stages/test_18_fb_ocr_e2e.py:GEMINI_MODELS`
4. This file's "Why this one" sections.
