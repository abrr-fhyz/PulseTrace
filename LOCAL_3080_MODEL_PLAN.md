# Local RTX 3080 Model Plan for PulseTrace

## Summary

PulseTrace can use a public RTX 3080 server for the main v2 AI workload by
running Ollama on that server and pointing the app at it with `OLLAMA_HOST`.
The repo already has Ollama support in `lib/backend.py`, `lib/llm.py`, and
`lib/embed.py`, so this is mostly deployment and configuration work rather
than a backend rewrite.

The recommended setup is:

- Run Ollama on the RTX 3080 server.
- Pull one JSON-reliable chat model and one embedding model.
- Expose Ollama through HTTPS with authentication, VPN, or SSH tunneling.
- Configure PulseTrace with `PULSETRACE_BACKEND=ollama` and
  `PULSETRACE_EMBED_BACKEND=ollama`.

## What Can Run on the 3080 Server

The v2 PulseTrace pipeline can send these AI tasks to the 3080-hosted Ollama
server:

- Seed query generation for a topic.
- Search expansion decisions between agent iterations.
- Cluster labeling.
- Per-cluster sentiment and stance scoring.
- RAG answers from the gathered corpus.
- Text embeddings for clustering and FAISS retrieval.

These tasks are already routed through the provider abstraction used by the v2
agent. When `PULSETRACE_BACKEND=ollama`, chat calls use Ollama's native
`/api/chat` endpoint with JSON mode. When embeddings use Ollama, `lib/embed.py`
calls Ollama's embedding endpoint and stores results in the existing JSONL
embedding cache.

## Scope Notes

This plan targets the v2 PulseTrace dashboard and agent loop described in
`README.md`.

Legacy v1 paths are different:

- `lib/catalogue.py` still uses OpenAI Vision for screenshot analysis.
- `lib/summary.py` still calls OpenAI directly for summaries.
- The legacy v1 buttons under "Legacy v1 tools" may still require OpenAI unless
  those modules are separately refactored.

So: v2 can run locally through the 3080 server today; fully local v1 OCR is a
separate project.

## Recommended 3080 Server Setup

Install Ollama on the RTX 3080 server:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Start or enable the Ollama service:

```bash
ollama serve
```

Pull a chat model and embedding model:

```bash
ollama pull qwen2.5:7b-instruct
ollama pull nomic-embed-text
```

Good model defaults for a 3080:

| Purpose | Recommended model | Notes |
|---|---|---|
| Chat / JSON tasks | `qwen2.5:7b-instruct` | Strong default for labels, stance, RAG, and query planning |
| Faster chat | `llama3.2:3b` | Lower quality, useful for testing |
| Higher quality chat | `qwen2.5:14b-instruct` | Try only if VRAM and latency are acceptable |
| Embeddings | `nomic-embed-text` | Existing repo default; fast and stable |
| Higher quality embeddings | `mxbai-embed-large` | Potentially better retrieval, more latency |

Confirm Ollama works on the server:

```bash
curl -s http://localhost:11434/api/tags
```

## Secure Public Exposure

Do not expose raw unauthenticated Ollama on the public internet.

Use one of these patterns:

1. HTTPS reverse proxy with authentication.
2. VPN between the PulseTrace machine and the 3080 server.
3. SSH tunnel from the PulseTrace machine to the 3080 server.

Recommended production-style shape:

```text
PulseTrace app -> HTTPS reverse proxy with auth -> Ollama on localhost:11434
```

If using a reverse proxy, keep Ollama bound to localhost on the server and let
the proxy handle TLS and access control.

If using an SSH tunnel from the PulseTrace machine:

```bash
ssh -L 11434:localhost:11434 user@your-3080-server
```

Then keep:

```bash
OLLAMA_HOST=http://localhost:11434
```

## PulseTrace `.env` Configuration

For a secured public Ollama endpoint:

```bash
PULSETRACE_BACKEND=ollama
PULSETRACE_EMBED_BACKEND=ollama
OLLAMA_HOST=https://your-3080-server.example.com
OLLAMA_CHAT_MODEL=qwen2.5:7b-instruct
OLLAMA_EMBED_MODEL=nomic-embed-text
OLLAMA_CHAT_TIMEOUT=600
OLLAMA_EMBED_TIMEOUT=300
```

If the endpoint requires a bearer token and the proxy forwards it to Ollama:

```bash
OLLAMA_API_KEY=your-token
```

If you want OpenAI as a fallback for chat only:

```bash
PULSETRACE_CHAT_CASCADE=ollama,openai
OPENAI_API_KEY=your-openai-key
```

For fully local/offline v2 behavior, omit OpenAI fallback and keep both chat and
embedding backends on Ollama.

## Validation Commands

From the PulseTrace machine, confirm the remote Ollama endpoint is reachable:

```bash
curl -s "$OLLAMA_HOST/api/tags"
```

Run the live Ollama backend tests:

```bash
PULSETRACE_BACKEND=ollama \
PULSETRACE_EMBED_BACKEND=ollama \
OLLAMA_HOST=https://your-3080-server.example.com \
.venv/bin/python -m pytest tests/test_ollama_backend.py -v -m slow
```

Run the default mocked suite:

```bash
.venv/bin/python -m pytest -v
```

Optionally run the full Facebook + Ollama path if Facebook cookies and
Playwright are ready:

```bash
FB_INTEGRATION=1 \
PULSETRACE_BACKEND=ollama \
PULSETRACE_EMBED_BACKEND=ollama \
OLLAMA_HOST=https://your-3080-server.example.com \
.venv/bin/python -m pytest tests/test_agent_e2e_fb_ollama.py -v -m slow
```

## Operational Notes

- First request after model cold start can be slow while weights load into GPU
  memory.
- Smaller chat models may occasionally return invalid JSON. If labels or RAG
  answers fail often, move from a 3B model to a 7B or 14B instruct model.
- Embedding caches are salted by backend and model tag, so switching embedding
  models will create fresh cache entries.
- Existing FAISS indexes under `data/runs/<run_id>/` are tied to the embedding
  model used when the run was created. Re-run the agent after changing embedding
  models.
- Keep `MAX_POSTS` and `MAX_ITERS` conservative until latency on the 3080 server
  is measured.

## Acceptance Criteria

- `LOCAL_3080_MODEL_PLAN.md` exists at the repo root.
- The plan explains which PulseTrace tasks can use the 3080 server.
- The plan documents Ollama setup, secure exposure, `.env` values, model
  choices, validation commands, and pytest commands.
- The plan clearly states that v2 is already Ollama-ready and legacy v1 OCR is
  outside this setup.
