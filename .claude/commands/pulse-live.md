---
description: PulseTrace live crawl — start a fresh agentic run, poll, then analyze (with fallback)
argument-hint: <topic> [sources: reddit,hn]
allowed-tools: mcp__pulsetrace__start_crawl_session, mcp__pulsetrace__get_crawl_status, mcp__pulsetrace__list_crawl_sessions, mcp__pulsetrace__get_sentiment_breakdown, mcp__pulsetrace__get_keyword_summary
---

Live target: **$ARGUMENTS**

Parse: topic = everything except a trailing comma-list of sources. Default sources = reddit, hn (reliable, no creds). Avoid facebook for a timed demo.

1. `start_crawl_session(topic, sources)` → announce the returned session_id.
2. Poll `get_crawl_status(session_id)` every few seconds. Narrate posts_collected + iterations as they climb. Stop polling when status == "completed" OR after ~6 polls.
3. If completed: `get_sentiment_breakdown(session_id)` + `get_keyword_summary(session_id)` and summarize the fresh result.
4. **Fallback** — if it stalls or stays pending, say "live ingestion still warming up — switching to a pre-loaded run" and call `list_crawl_sessions` to grab a recent completed session, then summarize that instead so the demo never dead-ends.

Keep narration tight. This shows real multi-source ingestion driven entirely through MCP.
