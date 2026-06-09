# Decisions Log

Append-only. Newest at top. Format: date — decision — reason.

## 2026-06-09
- **Orchestration layer = LangGraph graph wrapping `run_agent` (Plan B).** The graph's `crawl` node runs the full pipeline (`run_agent(close_bus=False)`); the graph adds engagement alerting + retry/recovery + scheduling on top. Real outputs, not a weaker parallel path. Details: `.claude/memory/orchestration.md`.
- **Single search box: dashboard "Run Agent" now POSTs `/api/agent/run`.** Orchestration wraps the agent, so the duplicate orchestration search box was removed; its card is now a live status panel off the same SSE stream. `/run` + `run_agent` preserved but UI-unused.
- **n8n = committed JSON workflow exports only, no instance.** Honors no-Docker non-goal; backs the submission claim with artifacts.
- **Engagement squash `1-exp(-raw/3.0)`** so unbounded `influence()` maps to 0–1 and the 0.75 alert threshold is meaningful.

## 2026-05-29
- **Add Ollama backend + slow-marked live test suite.** User has no OpenAI key, has 16 GB RAM + Ollama locally. `lib/backend.py` selects via `PULSETRACE_BACKEND`. New tests: `test_ollama_backend.py`, `test_fb_integration.py`, `test_agent_e2e_fb_ollama.py`, all behind `slow` marker; deselected by default. Setup in `.claude/memory/testing-with-ollama.md`. pytest-timeout=900.
- **Embed cache key salted with backend tag.** Prevents cross-backend cache poisoning (OpenAI 1536d vs Ollama 768d).
- **Add FB / X / IG connectors with honest caveats.** User confirmed FB is main target; willing to accept fragility on X / IG. Skeletons fail gracefully ([]). Live testing deferred for X / IG until creds available.
- **FacebookConnector uses Playwright + DOM scrape, not OCR.** v1 OCR pipeline preserved as separate CLI path. v2 connector is lighter and per-query.
- **Adopt `.claude/{memory,plans,rules,skills,specs}` layout.** Mirror readest-app convention. CLAUDE.md at root indexes it.
- **Branch v2 work to `shyan`.** Keep `v1.1` clean; merge later if v2 stabilizes.
- **No durable DB; per-run JSON + FAISS files.** Hackathon scope; SQLite would add ceremony without payoff.
- **`gpt-4o-mini` as default LLM** via `PULSETRACE_LLM_MODEL` env. Cheap, fast, JSON-mode reliable.
- **`text-embedding-3-small` for embeddings.** 1536-d, $0.02/1M tokens; cap at 500 posts/run.
- **HDBSCAN min_cluster_size=4.** Hackathon sample sizes are small; smaller min misses themes.
