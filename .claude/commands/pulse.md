---
description: One-shot PulseTrace demo — auto-chains MCP tools to analyze sentiment on a topic
argument-hint: <topic or session_id>
allowed-tools: mcp__pulsetrace__list_crawl_sessions, mcp__pulsetrace__get_sentiment_breakdown, mcp__pulsetrace__get_keyword_summary, mcp__pulsetrace__get_top_posts, mcp__pulsetrace__detect_coordination, mcp__pulsetrace__query_rag, mcp__pulsetrace__get_inference_result
---

You are demoing the **PulseTrace** sentiment-intelligence platform live to hackathon judges. Be fast, visual, and narrate each step in ONE short line before calling the tool. Target: under 90 seconds of tool calls.

Target: **$ARGUMENTS**

Run this chain against the PulseTrace MCP server. If `$ARGUMENTS` looks like a session_id (digits-hex), use it directly; otherwise call `list_crawl_sessions` and pick the newest session whose `topic` contains the words in `$ARGUMENTS` (case-insensitive). State which session you picked (id + topic + posts_count).

Then, in order:

1. **Sentiment** — `get_sentiment_breakdown(session_id)`. Report overall pos/neu/neg as percentages + confidence.
2. **Themes** — `get_keyword_summary(session_id)`. Show the top 3-4 clusters: theme label, post volume, sentiment lean.
3. **Loudest voices** — `get_top_posts(session_id, limit=3)`. One line each: author + engagement score + a short text snippet.
4. **Astroturf radar** — `detect_coordination(session_id)`. If any campaigns found, this is the headline: report n_authors, n_copies, score, sample_text. If none, say "no coordinated activity detected — organic conversation."
5. **Grounded Q&A** — `query_rag(session_id, "What is the main reason behind the dominant sentiment?")`. Show the cited answer.

Finish with a 2-sentence verdict: what the crowd thinks and whether the signal looks organic or manufactured.

Rules:
- Never invent numbers — only report what tools return.
- If a tool errors or returns empty, say so briefly and continue.
- No preamble. Start with the session pick.
