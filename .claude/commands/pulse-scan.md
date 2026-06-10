---
description: PulseTrace scan — sessions, sentiment, themes, and top voices for a topic
argument-hint: <topic or session_id>
allowed-tools: mcp__pulsetrace__list_crawl_sessions, mcp__pulsetrace__get_sentiment_breakdown, mcp__pulsetrace__get_keyword_summary, mcp__pulsetrace__get_top_posts
---

Scan target: **$ARGUMENTS**

Resolve the session: if `$ARGUMENTS` is a session_id use it; else `list_crawl_sessions` and pick the newest whose topic matches. State the pick (id, topic, posts_count).

Then call, narrating one line each:
1. `get_sentiment_breakdown(session_id)` → overall pos/neu/neg %, sample size, confidence.
2. `get_keyword_summary(session_id)` → table of clusters: theme | volume | sentiment lean.
3. `get_top_posts(session_id, limit=5)` → ranked voices: author | engagement | snippet.

End with a one-line read on the conversation. Report only real tool output.
