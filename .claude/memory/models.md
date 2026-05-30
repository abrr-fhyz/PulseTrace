---
name: Gemini model selection
description: Active prod chat/embed/vision model picks + pricing rationale (Dec 2025 verified)
type: project
---

# Model Selection — Production E2E (revised 2026-05-30 b)

> Verified live against the paid Gemini API (key prefix `AQ.Ab8R…`). Pricing
> cross-checked at https://ai.google.dev/gemini-api/docs/pricing on 2026-05-30.

## Active defaults

| Stage          | Model                       | Why                                                |
|----------------|-----------------------------|----------------------------------------------------|
| chat (label, stance, RAG, agent) | `gemini-2.5-flash-lite` | 3× cheaper than flash, latest stable, sufficient quality for JSON-mode label/stance |
| embeddings     | `gemini-embedding-001`      | Cheapest stable embed ($0.15/M), text-only is all we need |
| vision OCR     | `gemini-2.5-flash`          | flash-lite multimodal is weaker; OCR fidelity matters more than cost (1 call per screenshot) |

## Pricing (paid tier, Dec 2025)

```
gemini-2.5-flash-lite   $0.10 in / $0.40 out  per 1M tokens   ← chat default
gemini-2.5-flash        $0.30 in / $2.50 out  per 1M tokens   ← vision only
gemini-2.5-pro          $1.25 in / $10.00 out per 1M tokens   (not used)
gemini-embedding-001    $0.15  per 1M input tokens            ← embed default
gemini-embedding-2      $0.20 text / $0.45 image              (multimodal alt)
```

## Deprecation note

`gemini-2.0-flash` and `gemini-2.0-flash-lite` shut down **2026-06-01**. Anything
still pointing at them must move to 2.5-* before that date. Our defaults are
already 2.5-*.

## Cost math for typical run

- "Donald Trump Buffalo", 50 posts, 4 iters, 1 vision OCR per screenshot, 1 RAG turn.
- Chat ≈ 200k input + 30k output → ~$0.03 (flash-lite)
- Vision ≈ 10 OCR calls × ~5k input → ~$0.015 (flash)
- Embed ≈ 50k tokens → ~$0.008
- **Per run total ≈ $0.05.** 50 runs ≈ $2.50.

## Fallback cascade

`lib/dispatch.py` rotates every stage across all free providers
(groq → openrouter → llm7 → huggingface → gemini → pollen → ollama).
Gemini sits position-0 for paid-key users via `PULSETRACE_BACKEND=gemini`.
Cascade preserved so a Gemini outage degrades to free providers instead of
killing the run.

## Vision OCR config

`tests/stages/test_18_fb_ocr_e2e.py` and `lib/catalogue.py` use:
`[gemini-2.5-flash, gemini-2.5-flash-lite]`. Lite acts as per-request fallback
if flash 429s. Paid-tier 15-RPM no longer binding; courtesy `time.sleep(4)`
between OCR calls retained.

## Updating this doc

If you swap models, update:
1. `lib/backend.py:PROVIDERS["gemini"]` defaults
2. `.env.production.example:GEMINI_CHAT_MODEL` / `GEMINI_EMBED_MODEL` / `GEMINI_VISION_MODEL`
3. `tests/stages/test_18_fb_ocr_e2e.py:GEMINI_MODELS`
4. This file's "Active defaults" table + pricing.
