# Project Context

## Origin
Hackathon project: "PulseTrace — Sentiment Intelligence" in InfoTech/Social Media domain.
Brief in `init_plan.md` (gitignored). Pitch: turn social-media noise into structured intelligence.

## Phases
- **v1 (main branch, shipped):** Facebook-only Playwright scraper, screenshot capture, Gemini+OpenAI vision OCR, text summary. Manual CLI.
- **v2 (shyan branch, in progress):** Autonomous agent loop. Multi-source (Reddit, HN; FB optional). Embeddings + clustering. RAG Q&A. Live dashboard with topic graph and sentiment timeline.

## Key design decisions
- Reddit + HN over FB as primary demo sources — they have real APIs, no cookie fragility, demo-able in seconds.
- HDBSCAN over k-means as primary clustering — handles noise + variable cluster sizes. KMeans fallback when HDBSCAN labels everything as noise.
- OpenAI `text-embedding-3-small` over local embeddings — quality + zero infra. On-disk JSONL cache makes re-runs free.
- SSE over WebSocket — one-way agent → browser, simpler, no auth needed.
- FAISS IndexFlatIP — small N (≤500), exact search is fine, no quantization needed.
- Stop conditions: entropy delta < 0.05 OR MAX_ITERS=4 OR MAX_POSTS=500 OR LLM-signaled stop.

## Risks / known-fragile
- FB scraper depends on cookies in `info/` and FB DOM stability. Treat as best-effort source.
- LLM JSON output occasionally truncated → `chat_json` retries once, then raises.
- HDBSCAN can return all-noise on small/uniform corpora → fallback path is critical.

## Out of scope
Instagram (login hostile), Twitter/X (paid API), durable database, auth, hosted deploy, Docker.
