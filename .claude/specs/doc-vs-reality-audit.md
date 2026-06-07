# PulseTrace — Submission Doc vs. Actual Codebase Audit

> Date: 2026-06-07. Every claim in the 6-tab submission doc checked against the
> real repo (`requirements.txt` + source grep). Branch `feat/opinion`.
>
> **Legend:** ✅ accurate · ⚠️ partly true / misleading · ❌ not in the code (claimed but absent)

## TL;DR verdict

The doc describes a **much larger, different stack than what is built.** The real
app is a lean, file-based, single-process Flask app with a custom agent loop and a
Gemini-default multi-provider LLM router. Roughly **half** the doc's headline
technologies (Postgres/Supabase, MongoDB, Streamlit, Pydantic, JSON Schema, BM25/
hybrid/self-RAG, pgvector, sentence-transformers, n8n, LangGraph, DSPy, Pydantic-AI,
14-endpoint dual-MCP) **do not exist in the repository.** Several real, shippable
features (opinion-evidence dashboard, briefing PDF, coordination detection, replay,
multi-provider BYOK) are **missing from the doc.**

---

## Tab 1 — Project Info / Problem / Solution

| Claim | Reality | Status |
|---|---|---|
| Scans social media for any topic, extracts engagement, structured narrative | Agent loop does exactly this | ✅ |
| Sources: Facebook, Instagram, X | FB (Playwright), IG (instaloader), X (twikit) — **plus Reddit (PRAW), HN** | ✅ (understated) |
| OCR via Gemini vision + OpenAI; parses reactions/comments/metadata | Gemini vision OCR on FB screenshots (`lib/process.py`,`dispatch.py`) | ✅ |
| Compiles JSON reports + plain-language briefing with visuals | Per-run JSON + WeasyPrint briefing + Chart.js/Cytoscape | ✅ |

Tab 1 is **accurate.** (Solution text says "OpenAI" for OCR — OCR is Gemini; OpenAI/other providers handle text. Minor.)

---

## Tab 2 & Tab 5 — Data Lifecycle & Engineering

| Claim | Reality | Status |
|---|---|---|
| Web scraping public posts → private DB | Scrapes; stores **JSON files**, not a DB | ⚠️ |
| **Multi-worker Playwright, parallel browser instances** | Single authenticated session, batched capture; parallelism is **OCR ThreadPool**, not browsers | ❌ |
| Headed debug toggle | Playwright supports headed mode | ✅ |
| Automated Flows: **n8n / Airflow / cron / webhooks** | None present | ❌ |
| **BeautifulSoup** for HTML parsing | Not imported anywhere | ❌ |
| **Pandas** for tabular data | Not imported anywhere | ❌ |
| Unstructured parsed by OpenAI + Gemini vision | Gemini vision OCR; LLM text via router | ✅ |
| Output serializers: JSON, **CSV**, Python dataclasses | JSON ✅, dataclasses ✅ (`Post`), **CSV export not implemented** | ⚠️ |
| Batch LLM enrichment (10–20/call) | Batched stance/label (`lib/stance.py`,`label.py`) | ✅ |
| **Pydantic** models validate at ingest + post-enrich | **No Pydantic.** Plain `@dataclass` | ❌ |
| **JSON Schema** validation | Not used | ❌ |
| Custom cataloging module normalizes/indexes | `lib/catalogue.py` exists (provider catalogue, not record schema validation) | ⚠️ |
| **PostgreSQL via Supabase**, partitioned, engagement indexes | **No SQL DB.** Per-run JSON under `data/runs/<id>/` | ❌ |
| **MongoDB** tiered hot/cold collections | **No MongoDB** | ❌ |
| **Vector DB (pgvector)** | **FAISS** local index, not pgvector | ❌ |
| **Streamlit** dashboard | **Flask + Jinja** (`server.py`,`templates/index.html`) + Chart.js | ❌ |
| Chart.js viz | Chart.js present (CDN) | ✅ |
| Executive summary + influential users + top posts + keyword perf | Exec briefing + influence ranking + clusters | ✅ (no "keyword performance over window" view) |
| Classical ML (scikit-learn) + clustering/segmentation | HDBSCAN + KMeans fallback (`lib/cluster.py`) | ✅ |
| **Deep Learning (PyTorch/TF/JAX)** | None | ❌ |
| LLM Inference / RAG | FAISS dense RAG (`lib/rag.py`) | ✅ |
| Influence = engagement + recency decay (deterministic) | `lib/influence.py` exactly this | ✅ |
| Entropy-based convergence stop | `lib/agent.py` entropy + saturation | ✅ |
| Per-run JSON + SSE streaming pipeline | `lib/store.py` + `lib/events.py` | ✅ |
| sha1-keyed JSONL embedding cache, reuse on re-run | `lib/embed.py` `data/embed_cache.jsonl`, sha1 keys | ✅ |
| Models: `gpt-4o-mini` (PULSETRACE_LLM_MODEL), `text-embedding-3-small` | **Default is Gemini** (`gemini-2.5-flash-lite` chat, `gemini-embedding-001` embed). `gpt-4o-mini` only via openrouter/llm7 providers. **`PULSETRACE_LLM_MODEL` and `text-embedding-3-small` not in code** | ⚠️ |
| Custom agent orchestration (seed→fetch→embed→cluster→sentiment→expand→converge→persist→RAG) | Matches `lib/agent.py` precisely | ✅ |
| Outbound APIs: OpenAI, Gemini, **Supabase, MongoDB Atlas** | OpenAI/Gemini/OpenRouter/Groq/HF LLM APIs yes; **Supabase/Mongo APIs absent** | ⚠️ |
| Webhooks & **CSV/PDF exports** | PDF (WeasyPrint) ✅; CSV ❌; webhooks ❌ | ⚠️ |
| **GDPR compliant** | No compliance/privacy code | ❌ |
| Lineage/observability via SSE + JSON/FAISS artifacts | True | ✅ |

---

## Tab 3 & Tab 6 — Prompts / Tokens / Models / RAG / MCP

### Prompt & token strategy
| Claim | Reality | Status |
|---|---|---|
| CoT, few-shot, role separation, negative prompting, JSON scaffolding, prompt chaining | Strict-JSON prompts + staged chaining in `lib/llm.py`,`agent.py`,`evidence.py` (no formal few-shot exemplars stored) | ⚠️ broadly true |
| Temperature tuned by task (0–0.2 extract / 0.6–0.8 ideation) | `chat_json` defaults temp 0.2; no high-temp ideation path | ⚠️ |
| **Tiered routing** lightweight→Gemini/DeepSeek, heavy→Claude Opus/GPT-4o | Multi-provider router exists (`lib/backend.py`), but **no DeepSeek/Claude/GPT-4o runtime providers**; default Gemini | ⚠️ |
| Pre-filter HTML/OCR with **BeautifulSoup/Pandas** | Neither library present | ❌ |
| Batch enrichment 10–20/call; prompt caching | Batching ✅; embedding cache ✅; LLM prompt-cache not explicit | ⚠️ |

### Models claimed
| Model | Reality | Status |
|---|---|---|
| Gemini Pro/Flash (vision OCR) | Default provider; OCR via Gemini | ✅ |
| **DeepSeek** (structured text / R1,V3,Coder local) | No DeepSeek provider or reference | ❌ |
| **Claude** (Sonnet/Opus runtime) | Dev-time codegen only; not a runtime provider | ⚠️ (dev only) |
| **ChatGPT / GPT-4o** | `gpt-4o-mini` reachable via openrouter/llm7; GPT-4o proper not wired | ⚠️ |
| **Llama / Grok** | Llama via Groq/HF/Ollama defaults ✅; **Grok absent** | ⚠️ |
| Ollama local | Supported (`lib/backend.py`,`dispatch.py`) | ✅ |

### Retrieval / RAG
| Claim | Reality | Status |
|---|---|---|
| Naive RAG (chunk by post, embed, top-k) | FAISS `IndexFlatIP` over per-post embeddings | ✅ |
| **sentence-transformer** embeddings | Embeddings via provider API (Gemini/OpenAI), **no sentence-transformers** | ❌ |
| **pgvector in Supabase** | FAISS local file, no pgvector/Supabase | ❌ |
| **Self-RAG** reflective re-retrieval (≤2 loops) | Not implemented | ❌ |
| **Hybrid BM25 + dense, reciprocal rank fusion** | Pure dense; no BM25/RRF | ❌ |
| **Graph RAG / rerankers / agentic multi-step retrieval** | None (Cytoscape is viz only) | ❌ |
| Retrieval scoped by session/topic | Scoped per run_id | ✅ |

### MCP server
| Claim | Reality | Status |
|---|---|---|
| Server `pulsetrace-intel-server`, **14 endpoints**, 4 groups | `mcp_server.py`: **4 tools** (`analyze_topic`,`get_run`,`ask_corpus`,`detect_coordination`) + `list_runs` resource | ❌ |
| FastMCP SDK | FastMCP (`from mcp.server.fastmcp import FastMCP`) | ✅ |
| Transports: streamable-HTTP + SSE | `stdio` default + `streamable-http` env-toggle | ⚠️ |
| **Two composed servers** (data + intelligence) via `include()`, shared `schemas/` Pydantic package | Single `FastMCP("PulseTrace")`, no composition, no `schemas/`, no Pydantic | ❌ |
| Named tools start_crawl_session / get_posts_by_session / run_inference (LangGraph) / get_schema_validation_report / trigger_enrichment_batch … | **None of these exist**; real tools are the 4 above | ❌ |
| Clients: Claude Desktop, n8n; bearer-token auth, role separation | No auth layer, no n8n client | ❌ |

---

## Tab 4 & Tab 6 — Builders / Automation / Frameworks

| Claim | Reality | Status |
|---|---|---|
| Cursor / Claude Artifacts / Replit for dev | External dev tools — not verifiable from repo (plausible) | — |
| **n8n self-hosted automation backbone** | Not present | ❌ |
| **LangGraph stateful graph agents** (tab6 softened to "LangGraph-adjacent custom manifold") | Custom single agent loop only; no LangGraph | ❌ |
| Custom agent loop, single-agent, SSE events, strict-JSON wrapper, no planner/critic | Exactly matches `lib/agent.py`,`events.py`,`llm.py` | ✅ |
| Open-source stack: Flask, FAISS, HDBSCAN+sklearn, PRAW, Playwright, Instaloader, Twikit, OpenAI SDK, NumPy | All present in `requirements.txt` | ✅ |
| No LangChain/LlamaIndex | Correct — none | ✅ |
| Fine-tuning: none | Correct | ✅ |
| Eval: entropy convergence + citation grounding + low-recall retry heuristics | Matches | ✅ |
| Guardrails/safety: none | Correct | ✅ |
| Local LLMs: Ollama; ran DeepSeek R1/V3/Coder | Ollama wired ✅; **no DeepSeek evidence** (default ollama model `llama3.2:3b`) | ⚠️ |
| Agentic frameworks: **LangGraph, Pydantic-AI, DSPy** | None present | ❌ |
| AI-DLC: **Spec-Kit, Cline Memory Bank, AGENTS.md** | No Spec-Kit/Cline/AGENTS.md in repo (uses `.claude/` specs+plans) | ❌ |

---

## Real features the doc OMITS (should be added)

- **Opinion-Aware Evidence Dashboard** (PR #6): optional opinion → pro/con-biased
  queries → `evidence.json` with 5-axis evidence ranking + hybrid confidence +
  pro/con dual-screen views. Flagship new feature — doc says nothing.
- **Executive briefing PDF** via WeasyPrint (`lib/briefing.py`).
- **Coordination detection** (`lib/coordination.py`, MCP tool `detect_coordination`).
- **Replay** of a run by iteration (`lib/replay.py`).
- **Multi-provider BYOK router** (`lib/backend.py`,`catalogue.py`,`keys.py`):
  Gemini (default), OpenRouter, Groq, HuggingFace, Ollama, Pollen, LLM7.
- **Cytoscape topic graph** + live SSE pipeline + 4-view SPA.
- **Test suite**: 159 passed / 11 skipped.

## Accurate-as-written (keep)
Custom single agent loop · entropy convergence early-stop · FAISS dense RAG with
citations · HDBSCAN+KMeans clustering · deterministic influence scoring · sha1 JSONL
embedding cache · per-run JSON persistence · SSE streaming · strict-JSON LLM wrapper ·
no LangChain/LlamaIndex · no fine-tuning · Playwright/PRAW/twikit/instaloader sources.

---

## Recommendation

The doc reads as an **aspirational architecture**, not the shipped system. Two honest paths:

1. **Rewrite to match reality** (recommended for a verifiable submission): replace
   Streamlit→Flask, Postgres/Supabase/Mongo→per-run JSON, pgvector/BM25/self-RAG/RRF→
   FAISS dense naive RAG, 14-endpoint dual-MCP→4-tool single FastMCP, drop n8n/LangGraph/
   DSPy/Pydantic-AI/Pydantic/JSON-Schema/BeautifulSoup/Pandas/DeepSeek/Grok, fix model
   names (Gemini default + multi-provider router, not `gpt-4o-mini`/`text-embedding-3-small`),
   and **add the omitted real features** above.
2. **Keep as vision but label it**: move every ❌/⚠️ row into an explicit
   "Planned / Roadmap" section so judges can tell shipped from aspirational. Anything
   left in "current build" must be code-backed (judges can `grep`).

Either way: claims that are easy to falsify by reading the repo (Streamlit, Postgres,
MongoDB, 14 MCP endpoints, n8n, LangGraph, Pydantic) are the highest risk — fix those first.
