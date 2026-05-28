# PulseTrace v2 — Agentic Sentiment Intelligence

**Date:** 2026-05-29
**Branch:** `shyan`
**Status:** Approved design, ready for plan.

## 1. Goal

Evolve the existing Facebook-only scraper into an autonomous, multi-source sentiment intelligence platform. The user enters a topic; an LLM-driven agent iterates query → scrape → embed → cluster → re-query until coverage converges. Outputs include a topic graph, sentiment timelines, influence-ranked posts, a plain-language briefing, and a RAG Q&A surface.

## 2. Non-Goals

- Instagram and X/Twitter ingestion (login-hostile / paid API).
- Authentication, user accounts, persistence beyond JSON+FAISS files.
- Docker, Kubernetes, hosted deployment.
- Real-time streaming ingestion (batch loop is sufficient).

## 3. Existing System (Baseline)

- `main.py` — CLI dispatcher: `scrape | process | summarize`.
- `lib/scrape.py` + `lib/scraper.py` — Playwright Facebook scraper, hard-coded BD political keyword seed list.
- `lib/process.py` — Gemini/OpenAI vision OCR over screenshots.
- `lib/summarizer.py` + `lib/summary.py` — text summary over JSON.
- `server.py` — Flask, `/status`, `/run-command`. Fire-and-forget subprocess execution, no progress feedback.
- `templates/index.html` — static dashboard, three buttons + counts.

Gaps: no multi-source, no agent loop, no clustering, no sentiment per-cluster, no influence ranking, no RAG, no live progress, no visualizations beyond text.

## 4. Architecture

### 4.1 Module map

```
lib/
  connectors/
    __init__.py
    base.py              Connector ABC — fetch(query, limit) -> list[Post]
    facebook.py          Adapter wrapping existing scrape.py
    reddit.py            PRAW-based, primary demo source
    hn.py                Algolia HN Search API
  embed.py               EmbeddingClient — OpenAI text-embedding-3-small (batched)
  cluster.py             HDBSCAN over normalized embeddings; k-means fallback
  label.py               LLM names + describes each cluster
  stance.py              Per-post sentiment + stance vs cluster centroid
  influence.py           Engagement-weighted score; per-cluster top-N
  agent.py               Orchestrator loop: seed → fetch → cluster → expand → stop
  rag.py                 FAISS index build + ask(question) endpoint
  events.py              Process-local SSE pub/sub
  store.py               JSON-on-disk read/write for posts/runs/clusters
server.py                + /run, /events (SSE), /ask, /graph, /run-status
templates/index.html     + Chart.js, Cytoscape, Q&A box, SSE consumer
data/
  runs/<run_id>/posts.json
  runs/<run_id>/clusters.json
  runs/<run_id>/index.faiss
docs/superpowers/
  specs/                 this file
  plans/                 implementation plan (next step)
```

### 4.2 Data shapes

```python
Post = {
  "id": str,                  # source-prefixed: "reddit:t3_abc123"
  "source": "facebook"|"reddit"|"hn",
  "text": str,
  "author": str|None,
  "url": str|None,
  "ts": int,                  # unix seconds
  "reactions": int, "comments": int, "shares": int,
  "raw": dict,                # source-specific extras
}

Cluster = {
  "id": int,
  "label": str,               # short LLM-named theme
  "desc": str,                # 1-2 sentence summary
  "centroid": list[float],
  "members": list[str],       # post ids
  "sentiment": {"pos": float, "neu": float, "neg": float},
  "top_posts": list[str],     # post ids by influence
}

Run = {
  "id": str, "topic": str, "started_at": int, "ended_at": int|None,
  "queries": list[{"q": str, "source": str, "n": int, "iter": int}],
  "stop_reason": "converged"|"budget"|"manual",
  "metrics": {"posts": int, "clusters": int, "entropy": float},
}
```

### 4.3 Agent loop

```
seed_queries = llm.expand(topic)                    # ~5 diverse queries
while iter < MAX_ITERS and not converged:
    posts = parallel(connector.fetch(q) for q in queries)
    new_embeddings = embed(posts.text)
    clusters = hdbscan(all_embeddings)
    labels = llm.label_clusters(clusters)
    decision = llm.next_step(labels, gaps, budget_left)
        # → {"action": "expand"|"stop", "queries": [...]}
    entropy_delta = abs(H_t - H_{t-1})
    converged = entropy_delta < EPS or budget_hit
    queries = decision.queries
```

Termination: `MAX_ITERS=4`, `MAX_POSTS=500`, `EPS=0.05`, or LLM-signaled stop.

### 4.4 Influence score

```
influence(p) = log1p(reactions) + 2*log1p(comments) + 3*log1p(shares)
             + 0.5 * recency_decay(ts)
```

Per-cluster top-N for the briefing.

### 4.5 RAG

- FAISS `IndexFlatIP` over normalized embeddings, persisted per run.
- `/ask` retrieves top-k=8 posts, passes context + question to LLM, returns answer + cited post ids.

### 4.6 Live updates (SSE)

`lib/events.py` exposes a thread-safe pub/sub. The agent publishes typed events:

```
{"type": "iter_start", "iter": 1, "queries": [...]}
{"type": "posts_fetched", "source": "reddit", "n": 47}
{"type": "clustered", "k": 6}
{"type": "labeled", "clusters": [...]}
{"type": "done", "metrics": {...}}
```

Server `/events` is a `text/event-stream` endpoint streaming the queue.

### 4.7 HTTP API

| Method | Path | Purpose |
|---|---|---|
| POST | `/run` | Start a run. Body: `{"topic": str, "sources": [str]}`. Returns `{"run_id": str}` |
| GET | `/events?run_id=` | SSE stream of agent events |
| GET | `/graph?run_id=` | Returns clusters + edges (cosine sim > 0.5) for Cytoscape |
| POST | `/ask` | Body: `{"run_id": str, "q": str}`. RAG answer + citations |
| GET | `/status` | Existing endpoint, kept for compatibility |

### 4.8 Frontend

`templates/index.html` gains:

- Topic input + source toggles + Run button.
- Live log panel consuming SSE.
- Chart.js sentiment timeline (one line per cluster).
- Cytoscape topic graph (clusters as nodes sized by member count, edges as similarity).
- Briefing pane (rendered Markdown from existing summarizer enriched with cluster labels).
- Q&A box hitting `/ask`.

Keep existing buttons in a "Legacy" section.

## 5. Tech choices

- **Embeddings:** OpenAI `text-embedding-3-small` (1536d, batched 100). Caches to `data/embed_cache.jsonl` keyed by `sha1(text)`. Cap 500 posts/run → ~$0.01 budget.
- **Clustering:** `hdbscan` (`min_cluster_size=4`). Fallback `sklearn.cluster.KMeans` with `k = round(sqrt(n/2))`.
- **Vector index:** `faiss-cpu`.
- **Reddit:** `praw` (read-only auth via app credentials).
- **HN:** `requests` against `https://hn.algolia.com/api/v1/search`.
- **Frontend libs:** Chart.js, Cytoscape.js (CDN, no build step).
- **Stance/sentiment:** LLM batch call (8 posts/call) returning JSON `{sentiment, stance, confidence}`.

## 6. Failure modes + mitigations

| Failure | Mitigation |
|---|---|
| FB scraper breaks (cookie expiry, DOM change) | Reddit + HN run independently; FB optional via `sources` flag |
| OpenAI embed cost overrun | `MAX_POSTS=500`, persistent embed cache, batch=100 |
| HDBSCAN returns all-noise | Auto-fallback to KMeans |
| Agent loop infinite | Hard `MAX_ITERS=4` and `MAX_POSTS` caps |
| LLM JSON parse failure | `lib/llm.py` strict-JSON wrapper with one retry |
| Reddit rate limit | PRAW handles backoff; cap requests per query |

## 7. Testing strategy

- Unit: `lib/influence.py`, `lib/cluster.py` (with synthetic embeddings), `lib/agent.py` convergence math.
- Integration: Reddit connector against a known subreddit query, asserting non-empty + schema.
- Smoke: `python -m pulsetrace.smoke --topic "openai"` runs full loop with `MAX_POSTS=30`.
- No mocks for the LLM in the smoke run — real call, gated behind env var.

## 8. Incremental delivery (one commit per step)

1. Scaffold dirs + `requirements.txt` + `.gitignore` + spec/plan docs.
2. Connector ABC + Reddit connector + tests.
3. `embed.py` + `cluster.py` + `label.py`.
4. `influence.py` + `stance.py`.
5. `agent.py` orchestrator + smoke entrypoint.
6. `events.py` SSE + server endpoints (`/run`, `/events`, `/graph`, `/run-status`).
7. `rag.py` + `/ask` endpoint.
8. Frontend rewrite: SSE log, Chart.js, Cytoscape, Q&A.
9. HN connector + polish + README update + push.

Each step ends with a green smoke run where applicable.

## 9. Out-of-scope risks acknowledged

- Facebook ToS — scraper exists already; not expanding usage.
- LLM hallucination in briefing — citations from RAG mitigate.
- No durable storage — acceptable for hackathon scope.
