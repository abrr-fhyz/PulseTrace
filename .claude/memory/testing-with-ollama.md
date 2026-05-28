# Testing PulseTrace with Ollama + Facebook (Local-Only Setup)

This document describes how to run the rigorous test suite that exercises the
full PulseTrace pipeline against a local Ollama instance and a real Facebook
session — no OpenAI key required.

## What this gives you

Three test files, all marked `slow` and skipped by default:

| File | What it covers | Gating |
|---|---|---|
| `tests/test_ollama_backend.py` | Live calls to local Ollama: `chat_json`, `label_cluster`, `embed_texts`, cluster math over real embeddings | `PULSETRACE_BACKEND=ollama` + Ollama reachable |
| `tests/test_fb_integration.py` | Real Playwright run against `facebook.com/search/posts/?q=...`: returns posts, schema is valid, text is non-trivial | `FB_INTEGRATION=1` + valid `info/cookies.json` |
| `tests/test_agent_e2e_fb_ollama.py` | Full pipeline: FB connector → embed (Ollama) → cluster → label (Ollama) → store → RAG ask | all of the above |

The default fast suite (no `slow` marker) still runs everything mockable.

## Prerequisites

### 1. Ollama installed and serving

Install: <https://ollama.com/download>

Confirm running:
```bash
curl -s http://localhost:11434/api/tags | head
```

If you use a non-default host:
```bash
export OLLAMA_HOST=http://localhost:11434   # adjust if different
```

### 2. Pull the models

Recommended for 16 GB RAM:
```bash
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

These map to defaults in `lib/backend.py`. Override with:
```bash
export OLLAMA_CHAT_MODEL=qwen2.5:3b           # any JSON-capable chat model
export OLLAMA_EMBED_MODEL=nomic-embed-text    # any Ollama embedding model
```

If you have headroom, `qwen2.5:7b-instruct` or `llama3.1:8b` produce noticeably
better cluster labels — at the cost of seconds per call.

### 3. Facebook cookies

Log into Facebook in a normal browser. Use a cookie-export extension
(e.g. "Cookie-Editor" for Chrome / Firefox) and export the `facebook.com`
cookies as JSON. Save to:
```
info/cookies.json
```

The connector loads this via Playwright. **Use a throwaway account** — FB flags
automated sessions and may disable accounts. Do not point this at your main.

### 4. Playwright Chromium

```bash
.venv/bin/python -m playwright install chromium
```

This is ~150 MB and only required for FB tests.

### 5. Test dependencies

Already in `requirements.txt`:
```bash
.venv/bin/pip install -r requirements.txt
```

This adds `pytest-timeout` (default 900 s per test) — generous to accommodate
local LLM latency.

## Running the tests

### Default (fast, mocked) suite

```bash
.venv/bin/python -m pytest -v
```

All `slow` tests are skipped via `addopts = -m "not slow"` in `pytest.ini`.

### Ollama backend tests only

```bash
export PULSETRACE_BACKEND=ollama
.venv/bin/python -m pytest tests/test_ollama_backend.py -v -m slow
```

Expect ~30–90 s total on `llama3.2:3b` + `nomic-embed-text`.

### Facebook integration only

```bash
export FB_INTEGRATION=1
.venv/bin/python -m pytest tests/test_fb_integration.py -v -m slow
```

Optional tuning:
```bash
export FB_HEADLESS=0            # show the browser; default 1 (headless)
export FB_TEST_QUERY=technology # default "technology"
export FB_TEST_SCROLLS=3        # default 3 (more = more posts, more time)
```

If the test fails with **"FB returned 0 posts — cookies stale or selectors drifted"**:

1. Re-export `info/cookies.json` from a fresh browser session.
2. If still empty: FB has likely changed its DOM. Open
   `lib/connectors/facebook.py` and adjust the locator in `_scrape()`. The
   current selector is `div[role="article"]`.

### Full end-to-end (FB + Ollama)

```bash
export FB_INTEGRATION=1
export PULSETRACE_BACKEND=ollama
.venv/bin/python -m pytest tests/test_agent_e2e_fb_ollama.py -v -m slow
```

Expect ~3–10 minutes on a 16 GB machine. The test caps the run at
`MAX_POSTS=20` / `MAX_ITERS=1` to keep it tractable.

### Run everything (including slow)

```bash
export FB_INTEGRATION=1
export PULSETRACE_BACKEND=ollama
.venv/bin/python -m pytest -v -m "slow or not slow"
```

## Environment variable reference

| Variable | Default | Purpose |
|---|---|---|
| `PULSETRACE_BACKEND` | `openai` | Set to `ollama` to use local models |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_CHAT_MODEL` | `llama3.2:3b` | JSON-capable chat model |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model |
| `OLLAMA_CHAT_TIMEOUT` | `600` | Seconds for one chat call |
| `OLLAMA_EMBED_TIMEOUT` | `300` | Seconds for one embedding call |
| `FB_INTEGRATION` | unset | Set to `1` to enable FB tests |
| `FB_HEADLESS` | `1` | `0` to show the browser |
| `FB_TEST_QUERY` | `technology` | Search query for FB tests |
| `FB_TEST_SCROLLS` | `3` | Times to wheel-scroll the FB feed |

## Troubleshooting

**`ConnectionError` to `localhost:11434`** — Ollama isn't running. Start with
`ollama serve` or restart the desktop app.

**Chat returns `{}` or fails to parse** — Smaller models occasionally ignore
`format=json`. Retry the test, switch to a 7B+ model, or shorten the prompt.

**Embeddings shape mismatch** — The cache is salted with the backend tag, so
switching `OLLAMA_EMBED_MODEL` automatically invalidates old entries. If FAISS
indexes are still around from a different model, delete `data/runs/<id>/`.

**FB Playwright fails to launch** — Run
`.venv/bin/python -m playwright install chromium` once; missing system libs
fixable with `.venv/bin/python -m playwright install-deps`.

**Account got locked / suspicious activity email** — Don't proceed. Use a
fresh throwaway account.

**Tests time out** — Bump `timeout = 900` in `pytest.ini` or set
`OLLAMA_CHAT_TIMEOUT` higher. First call to a model after a cold start can take
30–60 s while Ollama loads weights into RAM.

## What "passing" looks like

On a clean 16 GB box with `llama3.2:3b` + `nomic-embed-text` warm:

- `test_ollama_backend.py`: 5/5 pass in ~60 s
- `test_fb_integration.py`: 2/2 pass in ~30 s (depends on FB)
- `test_agent_e2e_fb_ollama.py`: 2/2 pass in ~4 minutes; the second test
  (`test_rag_over_fb_run`) may skip if fewer than 4 posts came back

Empty FB results are not a code failure — they're a signal that either cookies
expired or selectors drifted. The test will tell you which.
