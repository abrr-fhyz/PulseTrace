# PulseTrace — 3-Minute Hackathon Demo (Claude CLI + MCP)

Drive the whole platform through Claude Code's MCP integration. The `pulsetrace`
MCP server (`.mcp.json`) exposes **15 real, pipeline-wired tools**. No mock data —
every number comes from real scraped runs in `data/runs/`.

## 0. One-time setup (do before judges arrive)

```bash
cd /home/shyan/Desktop/FBScraper
claude            # launches in this dir → auto-loads .mcp.json → pulsetrace MCP on (stdio)
```

First run, approve the `pulsetrace` server once. The 5 slash commands below
pre-approve their tools, so the live demo has **zero permission prompts**.

Verify tools are live:
```
/mcp            # should list: pulsetrace (15 tools)
```

## 1. The commands (all pre-wired, just type)

| Command | What it shows | Best session |
|---------|---------------|--------------|
| `/pulse <topic>` | **One-shot.** Auto-chains sessions → sentiment → themes → voices → astroturf → cited Q&A | `brazil` |
| `/pulse-scan <topic>` | Sentiment + theme clusters + top voices | `brazil` |
| `/pulse-ask <topic> \| <question>` | RAG cited answer grounded in real posts | `brazil` |
| `/pulse-coord <topic>` | Astroturf / coordinated-campaign radar | `Fable 5` |
| `/pulse-live <topic>` | Fresh crawl (reddit+hn), polled live, with fallback | any |

## 2. Verified demo sessions (loaded, instant, offline-safe)

- **`brazil`** → `1781086484-b313e8` — "Brazil's 2026 World Cup squad", 237 posts.
  Sentiment 52% pos / 47% neu, confidence 0.8, has `index.faiss` → **RAG works (3.5s, 6 citations)**.
- **`Fable 5`** → `1781066904-29a3b7` — coordination signal: 1 campaign, score 1.117. The astroturf headline.

Topic words resolve automatically — judges can type `/pulse brazil` and the command
finds the session. Pass a raw `session_id` to be deterministic.

## 3. The 3-minute script

**[0:00] Hook** — "PulseTrace listens to social platforms and tells you what a crowd
actually thinks — and whether that opinion is real or manufactured. All through MCP,
so any agent can drive it."

**[0:20] One command does it all:**
```
/pulse brazil
```
Watch Claude call the MCP tools in sequence and narrate. ~60–90s.

**[1:50] The moat — astroturf detection:**
```
/pulse-coord Fable 5
```
"Same post, 3 accounts, tight window — manufactured consensus, flagged as a lead."

**[2:30] Grounded, cited Q&A (no hallucination):**
```
/pulse-ask brazil | Will Neymar make the squad?
```
"Every claim cites a real scraped post."

**[2:55] Close** — "Sentiment + provenance + coordination radar, all MCP-native."

## 4. Raw-prompt mode (most 'agentic' feel)

Skip the commands; let Claude pick tools organically:
> "Use the pulsetrace tools to analyze fan sentiment on Brazil's 2026 World Cup squad,
>  then check whether any of the buzz looks coordinated."

## 5. Fallbacks (don't get caught)

- **Live scrape stalls?** `/pulse-live` auto-falls back to a pre-loaded run. Or just use `/pulse brazil`.
- **Network down?** The 9 file-only tools (sentiment, themes, voices, astroturf, schema) need
  **no network** — fully offline. Only RAG/inference call the LLM.
- **A tool errors?** Commands are told to report briefly and continue — the chain won't dead-end.

## 6. App-embedded MCP (Docker / local web app)

The MCP server also auto-starts with the Flask app (streamable-http on **:8000**),
so remote agents can hit the same tools without Claude CLI:

- Local: `python server.py` → MCP spawned on `:8000` (via `lib/mcp_autostart.py`).
- Docker: `docker compose up` → gunicorn `when_ready` spawns it once → `:8000` published.
- Toggle: `PT_MCP_AUTOSTART=0` to disable. Port: `PULSETRACE_MCP_PORT`.

Endpoint: `http://<host>:8000/mcp` (streamable-http). Stdio path (Claude CLI) is unchanged.
