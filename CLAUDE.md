# PulseTrace — Project Memory

> Project memory for Claude Code. Compact. Real source of truth = `.claude/`.

## What this is
PulseTrace v2: agentic sentiment intelligence platform. User gives topic → LLM-driven agent loops over multi-source social fetch → embed → cluster → label → expand queries until coverage converges → topic graph, sentiment timeline, RAG Q&A.

V1 (preserved): Facebook scraper (Playwright) + Gemini/OpenAI vision OCR + text summary. CLI: `python main.py {scrape|process|summarize}`.

## Stack
- Python 3.12, Flask + SSE, Playwright (existing scraper), OpenAI SDK, PRAW, requests, numpy, scikit-learn, hdbscan, faiss-cpu.
- Frontend: Jinja template + Chart.js + Cytoscape.js (CDN, no build step).

## Layout
```
.claude/
  memory/         project context, decisions
  plans/          implementation plans (YYYY-MM-DD-*.md)
  rules/          coding standards + conventions
  skills/         local project skills
  specs/          design specs (input to plans)
lib/
  connectors/     pluggable source connectors (base, reddit, hn, facebook, x, instagram)
  embed.py        cached OpenAI embeddings
  cluster.py      HDBSCAN + KMeans fallback + entropy
  llm.py          strict-JSON chat wrapper
  label.py        cluster naming
  stance.py       per-cluster sentiment
  influence.py    engagement + recency scoring     (planned)
  agent.py        orchestrator loop                (planned)
  rag.py          FAISS + cited Q&A                (planned)
  events.py       SSE pub/sub bus                  (planned)
  store.py        per-run JSON persistence         (planned)
  scrape.py/scraper.py/process.py/summarizer.py/summary.py   v1 FB pipeline
main.py           v1 CLI dispatcher
server.py         Flask app (v2 endpoints planned)
templates/
  index.html      dashboard
tests/            pytest, real LLM mocks
data/runs/<run_id>/  posts.json, clusters.json, run.json, index.faiss
```

## Active work
- Branch: `shyan`
- Spec: `.claude/specs/2026-05-29-pulsetrace-v2-design.md`
- Plan: `.claude/plans/2026-05-29-pulsetrace-v2.md`
- Status: Tasks 1–6 done (scaffold, connectors, embed/cluster/llm/label/stance). Next: influence → agent → RAG → server endpoints → dashboard → HN polish → push.

## Run locally
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env  # fill OPENAI_API_KEY, REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET
.venv/bin/python server.py
# open http://localhost:5000
```

Tests:
```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/ -v
```

## Rules cheat sheet (full: `.claude/rules/`)
- Small focused files. One responsibility per module.
- TDD for pure logic (influence, cluster, parse). No mocks for FB scraper paths.
- Frequent commits. One concern per commit. Conventional commit prefix.
- No `# what this does` comments. WHY only when non-obvious.
- LLM JSON path always goes through `lib/llm.py:chat_json` (strict + retry).
- Env vars: never hardcode keys; use `python-dotenv`.

## Non-goals (won't build)
Auth, durable DB, Docker, hosted deployment.

## Source reliability
- Reddit + HN: reliable, always on.
- Facebook (main target): fragile real scraper, needs `info/cookies.json`.
- Twitter/X + Instagram: skeletons wired, awaiting creds. Return `[]` until configured.
- See `.claude/memory/source-risks.md` for full caveats.
