# Coding Standards

## Python

- Target Python 3.10+ syntax. `from __future__ import annotations` at top of every module.
- Type hints required on public functions. Use built-in generics (`list[str]`, not `List[str]`).
- `dataclass` for plain records; no Pydantic unless validating external input.
- Avoid global state. If shared (e.g. event bus), make it explicit and singleton-named (`BUS`).
- Module-level imports only — never deferred imports for testing convenience (except heavy optional deps).
- Catch narrow exceptions. Never bare `except:`.

## File size
- Soft cap ~200 lines per module. Split by responsibility, not by layer.
- One public ABC + concrete impls in same package, separate files.

## Tests
- TDD for pure logic: math, parsing, scoring, convergence.
- Mock external IO (HTTP, OpenAI). Use `unittest.mock.patch`.
- Smoke tests gated behind env vars (`REDDIT_CLIENT_ID`, `OPENAI_API_KEY`) — `pytest.skipif`.
- Test file path mirrors module path: `lib/foo.py` ↔ `tests/test_foo.py`.

## Commits
- One concern per commit. Don't bundle unrelated changes.
- Conventional Commits: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`.
- Subject ≤72 chars. Body explains *why* if non-obvious.
- Always include `Co-Authored-By` trailer when Claude generates the commit.

## Comments
- Default: write none.
- Add only when *why* is non-obvious (invariant, workaround, hidden constraint).
- Never describe *what* the code does — name things so the code self-describes.

## LLM calls
- All structured LLM output goes through `lib/llm.py:chat_json`.
- Always `response_format={"type": "json_object"}` + one retry on parse failure.
- Temperature 0.2 default. Don't tune unless the task demands it.
- Cap `max_tokens` per call. Embedding budget cap: `MAX_POSTS=500` per run.

## Errors / fallbacks
- Connector failures must not kill the agent loop — log + continue.
- Cluster method failure (HDBSCAN) falls back to KMeans automatically.
- Empty inputs return empty outputs, not errors (zero-row arrays, empty dicts).

## Frontend
- No build step. CDN scripts only (Chart.js, Cytoscape).
- SSE for live updates. Never poll.
- One `index.html` — keep it readable. No SPA framework.

## Env / secrets
- Read via `os.environ.get("KEY", "")` — never raise at import time.
- `.env` is gitignored. `.env.example` lists keys without values.
