# PulseTrace — MCP Integration Spec

> Author: strategy pass, 2026-06-06.
> Goal: expose PulseTrace's moat (FB vision-OCR, coordination radar, provenance, cited Q&A) over the **Model Context Protocol** so any AI agent (Claude Desktop, Cursor, custom) can call it.
> Companion: `.claude/specs/2026-06-06-winning-strategy-4axis.md` (this serves Axis 3 latest-tech + Axis 4 distribution).

---

## TL;DR — the bet

Turn the product into **infrastructure**. Killer framing:

> **"PulseTrace MCP — give any AI agent eyes on Facebook misinformation."**

Claude Desktop user types *"is this rumor coordinated on FB?"* → calls the server → vision-OCR reads memes no other MCP can see. That sentence wins demo + business.

---

## Two directions

### Direction A — PulseTrace AS MCP server ★ (build this)
Expose capabilities as MCP tools/resources. Thin wrapper over existing `lib/` functions. No engine rewrite.

### Direction B — PulseTrace AS MCP client (skip for demo)
Add an MCP connector pulling from external MCP data servers into the agent loop (`lib/connectors/mcp.py` implementing the `Connector` ABC). It's plumbing, not moat. Backlog.

---

## Tools to expose (Direction A)

| MCP tool | Maps to existing | Notes |
|----------|------------------|-------|
| `analyze_topic(topic, sources)` | `agent.py:run_agent` | long-running → return `run_id`, client polls `get_run` |
| `get_run(run_id)` | `store.py` read | clusters, sentiment, status |
| `ask_corpus(run_id, question)` | `rag.py:ask` | cited Q&A — grounded, not theater |
| `detect_coordination(run_id)` | `dedup.py:near_dupe_keep` + author grouping | **unique** — astroturf/coordination radar |
| `scrape_facebook(query)` | `connectors/facebook.py:fetch_many` | **the moat** — vision-OCR FB rendered memes |
| `trace_provenance(run_id, claim)` | planned `lib/claims.py` | Patient Zero flagship |
| `get_briefing(run_id)` | `briefing.py:build` | returns PDF/HTML artifact |

### Resources (read-only)
- `pulsetrace://runs` — run registry list (ties to the `/runs` registry already on the roadmap)
- `pulsetrace://run/{id}/posts` · `/clusters` · `/claims`

---

## Architecture

- **New file:** `mcp_server.py` (~150 LoC). Each tool ≈ 10 lines calling a function that already exists.
- **SDK:** Python MCP SDK / **FastMCP** — `@mcp.tool()` decorators. Confirm current API via context7 before coding.
- **Transport:**
  - **stdio** for local Claude Desktop (registry entry in client config).
  - **HTTP/SSE** reusing the existing Flask + SSE box (`server.py`, `events.py:BUS`) for hosted/remote agents.
- **Long-running runs:** `analyze_topic` returns `run_id` immediately; progress streams over the existing SSE bus; `get_run` polls state. Never block the tool call on a full agent run.
- **Auth / keys:** BYOK per call or server-side key; never log keys; scrub from error payloads (mirror existing `_byok_apply/_byok_restore`).

---

## Why it serves all four axes
- **Look smart (1):** "not an app — a capability any agent plugs into."
- **Unique (2):** only MCP server that reads FB rendered memes + flags coordination.
- **Latest tech (3):** MCP is the 2025 interop standard; demonstrable, not buzzword.
- **Business (4):** new distribution — listed in MCP registries = inbound funnel; hosted tier sells server-side runs. "Open-source MCP core, hosted intelligence."

---

## Build plan
- **Phase 1 (~1d):** `mcp_server.py` with 3 zero-risk tools that work today — `analyze_topic`, `get_run`, `ask_corpus` — over stdio. Test against Claude Desktop.
- **Phase 2 (~0.5d):** `detect_coordination` (reuses `dedup.py`) + `pulsetrace://runs` resource.
- **Phase 3:** `scrape_facebook` (gated on fresh cookies) + `trace_provenance` (after `lib/claims.py` lands) + HTTP/SSE transport.

---

## First move
Scaffold `mcp_server.py` with `analyze_topic` + `get_run` + `ask_corpus` (stdio, FastMCP). Pull current FastMCP docs via context7 first so the API is right.
