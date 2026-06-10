---
description: PulseTrace cited Q&A — ask a question grounded in a session's real posts
argument-hint: <topic-or-session_id> | <question>
allowed-tools: mcp__pulsetrace__list_crawl_sessions, mcp__pulsetrace__query_rag
---

Input (pipe-separated): **$ARGUMENTS**

Split on `|`: left = topic or session_id, right = the question. If there is no `|`, treat the whole thing as the question and use the newest session from `list_crawl_sessions`.

Resolve the session (id directly, or newest topic match via `list_crawl_sessions`), state the pick, then call `query_rag(session_id, question)`.

Show:
- **Answer** — the grounded answer verbatim.
- **Evidence** — the citations / retrieved posts that back it (author + snippet).

This proves the answer is sourced from real scraped posts, not the model's prior. Do not add facts the citations don't support.
