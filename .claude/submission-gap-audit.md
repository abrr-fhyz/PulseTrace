# Submission Gap Audit — Form Claims vs Actual Code

> Cross-checked the Data Lifecycle / AI-DLC submission form against the real
> codebase (`lib/`, `requirements.txt`, `mcp_server.py`, `server.py`) and the
> verified `.claude/memory/project-snapshot.md` (audited 2026-06-07).
> Audited 2026-06-09. Legend: ❌ claimed-not-built · ⚠️ partial/misstated · ✅ true.

## TL;DR
Load-bearing fabrications a judge could disprove in minutes:
**SQL/Supabase + MongoDB storage, MCP "14 endpoints / 4 groups",
LangGraph, n8n, DeepSeek at runtime, Streamlit.**
Reality: stateless file-based JSON + FAISS, single 4-tool MCP server,
custom single-loop agent, Flask/Jinja dashboard, Gemini-default LLM.
(Hybrid + self-reflective RAG is now BUILT — see RAG section — on branch
`refactor/hybrid_RAG`.)

---

## NOT BUILT — claimed but absent

### Storage (Q4) — biggest gap
- ❌ PostgreSQL / Supabase. No `supabase`/`psycopg` dep. Storage = per-run JSON `data/runs/<id>/`.
- ❌ MongoDB tiering (hot primary / cold compacted collections). No `pymongo`.
- ❌ pgvector / Pinecone / Weaviate. Vector store = local FAISS `IndexFlatIP` file.
- ❌ Table partitioning by crawl-date/topic-ID, engagement indexes, leaderboard queries — no DB at all.

### RAG architecture (Q-RAG)
- ✅ Hybrid search (BM25 + dense). Built in `lib/retrieve.py` (`rank_bm25` BM25Okapi + FAISS dense).
- ✅ Reciprocal rank fusion (RRF). `lib/retrieve.py:rrf_merge`, RRF_K=60.
- ✅ Self-reflective layer (LLM-judge confidence → query refine → re-retrieve, ≤2 iters). `lib/rag.py:ask`.
- ❌ sentence-transformer embeddings. Uses OpenAI/Gemini embedding API.
- ❌ Session/topic-scoped pgvector retrieval. FAISS per-run file, no SQL scoping.
- ⚠️ Reranker — `lib/rerank.py` exists (LLM rerank + relevance blend 0.60/0.20/0.15/0.05), but NOT Cohere/BGE.

### MCP (Q-MCP) — count inflated
- ❌ "14 endpoints / 4 groups (A–D)". Actual = **4 tools** + 1 resource.
  - Real tools: `analyze_topic`, `get_run`, `ask_corpus`, `detect_coordination`; resource `pulsetrace://runs` (`list_runs`).
- ❌ Two composed servers (`pulsetrace-data-server` + `pulsetrace-intelligence-server`) via `include()`. Single `FastMCP("PulseTrace")`.
- ❌ All 14 named tools fabricated: `start_crawl_session`, `get_crawl_status`, `cancel_crawl_session`, `list_crawl_sessions`, `get_posts_by_session`, `get_post_detail`, `get_top_posts`, `get_keyword_summary`, `run_inference`, `get_inference_result`, `query_rag`, `get_sentiment_breakdown`, `get_schema_validation_report`, `trigger_enrichment_batch` — none exist.
- ❌ Bearer-token auth / role-based read-vs-write separation. Not implemented.
- ❌ MCP client = n8n. No n8n.

### Orchestration / Agent frameworks (Q7)
- ❌ LangGraph (graph nodes, conditional edges, persistent state). Custom single loop in `lib/agent.py`. No `langgraph` dep.
- ❌ n8n self-hosted workflows / webhooks / scheduled re-crawls / engagement-threshold alerts / failure-recovery retries. None.
- ❌ Pydantic-AI. No `pydantic` even installed.
- ❌ DSPy prompt optimization. Absent.
- ⚠️ Scheduling/triggers (Q7) — correctly left blank; none built.

### Parsing / Cleaning / Validation (Q3)
- ❌ BeautifulSoup HTML parsing. Not used.
- ❌ Pandas in-memory tabular handling. Not a dep.
- ❌ Pydantic validation at ingestion + post-enrichment. No pydantic.
- ❌ JSON Schema validation of persisted docs. Absent.
- ❌ "Custom cataloging module" normalize/index. No such module.

### Visualization (Q5)
- ❌ Streamlit. Frontend = single Flask Jinja `templates/index.html` + Chart.js / Cytoscape via CDN.
- ❌ Streamlit dropdowns / date-range filter / sort-by-reaction drill-down. Not built.

### Models (Q-LLM)
- ❌ DeepSeek (R1/V3/Coder) at runtime. Not in `lib/backend.py` router.
- ❌ Grok. Absent.
- ❌ Tiered cost-routing (Flash/DeepSeek cheap → Opus/GPT-4o expensive). Router exists but no auto cost-tier logic.
- ❌ Ollama-ran-DeepSeek. Router ollama target = `llama3.2:3b`, not DeepSeek.
- ⚠️ Default runtime LLM = **Gemini** (`gemini-2.5-flash-lite` chat, `gemini-embedding-001`), NOT OpenAI as Q6 states.

### Token optimization (Q-token)
- ❌ Gemini context caching. Not implemented.
- ❌ Rolling summary memory. Absent.
- ⚠️ Prompt caching of static system tokens — claimed, not in code. Only real cache = embedding sha1-keyed JSONL (`data/embed_cache.jsonl`).

### Frontend AI builders
- ❌ Replit Agent — no repo evidence.
- ⚠️ Claude Artifacts / Cursor — dev-time tools, unverifiable from repo (plausible, not provable).

### AI-DLC
- ❌ GitHub Spec-Kit, Cline Memory Bank, AGENTS.md. Repo uses `.claude/` + `CLAUDE.md` instead.

### Guardrails / Fine-tuning
- ✅ Form says NONE for both. Matches reality.

---

## Actually TRUE (built — safe to claim)
Flask + SSE backend; Playwright FB scraper (single authenticated session, batched);
Reddit=PRAW, HN=API, X=twikit, Instagram=instaloader connectors; Gemini Flash/Pro
vision OCR on FB screenshots; OpenAI/Gemini embeddings w/ sha1 JSONL cache;
HDBSCAN + KMeans fallback clustering; entropy + saturation convergence early-stop;
deterministic influence scoring (engagement + recency decay); FAISS dense RAG +
cited Q&A; executive briefing HTML + PDF (WeasyPrint); opinion-aware evidence
dashboard (pro/con, 5-axis claim ranking); coordination/astroturf detection
(`lib/coordination.py`); custom single-loop agent (`lib/agent.py`); LLM rerank
(`lib/rerank.py` + `lib/relevance.py`); 4-tool FastMCP server (stdio + streamable-http).

---

## Recommended action
Either **(a)** rewrite the form to match the true stateless file-based + FAISS +
Gemini + 4-tool-MCP build, or **(b)** if the form must stand, build the missing
high-value pieces in priority order: hybrid/self-reflective RAG → real MCP tool
expansion → optional Postgres/pgvector persistence. Do NOT ship the form as-is with
the 14-MCP / LangGraph / n8n / DeepSeek / Supabase claims — fastest to disprove.
