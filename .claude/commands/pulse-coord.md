---
description: PulseTrace astroturf radar — detect coordinated / inauthentic campaigns
argument-hint: <topic or session_id> [min_authors]
allowed-tools: mcp__pulsetrace__list_crawl_sessions, mcp__pulsetrace__detect_coordination, mcp__pulsetrace__get_post_detail
---

Target: **$ARGUMENTS**

Parse: first token = topic or session_id; optional second integer = min_authors (default 3).

Resolve the session (id directly, or newest topic match via `list_crawl_sessions`); state the pick. Then `detect_coordination(session_id, min_authors)`.

If campaigns found, for the top one report:
- **Score** (0-1 suspicion), **distinct authors**, **near-identical copies**, **time span**.
- The shared **sample_text**.
- The author handles involved.

Frame it as an *investigative lead, not a verdict* — near-identical posts from many accounts in a tight window. If none found, state clearly: organic conversation, no coordination signal.

This is the moat: detecting manufactured consensus, not just measuring sentiment.
