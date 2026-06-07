# PulseTrace — Winning Strategy (4-Axis Prep)

> Author: strategy pass, 2026-06-06.
> Goal: prepare the project to win on the four axes the user flagged as most important:
> **(1) look smart / talk nicely · (2) solve one problem uniquely · (3) latest technology · (4) business / monetization.**
>
> Companion docs: `feature/features_plan.md` (full PM portfolio), `feature/optimization_plan.md` (perf), `.claude/plans/2026-05-29-pulsetrace-v2.md` (build plan).
> This doc distills those into a ranked, code-grounded prep sheet keyed to the four axes.

---

## Axis 1 — Look smart, talk nicely (polish + presentation)

Judges score the demo, not the repo. Make the invisible agent loop visible and speak human.

| Move | Code anchor | Effort |
|------|-------------|--------|
| **Glass-box agent** (S2) — agent "thinks out loud" on screen | `events.py:BUS` already streams; add a rationale string per decision in `agent.py:_llm_next` ("coverage 0.61, economic angle thin → expand") | ~1d |
| **Plain-language microcopy** | replace jargon: "entropy plateau" → "coverage leveling off". `templates/index.html` | ~1h |
| **Stage stepper** `Fetch → Cluster → Label → Stance → Brief` w/ live counts | render existing SSE events as a stepper, not a raw log | ~0.5d |
| **Dark mode + design tokens** | CSS vars; borrow the briefing palette | ~0.5d |

Talk-nice checklist: exec summary first · cost line ("this run ~$0.02") · cited evidence clickable · empty/error states with a next action, never a silent blank.

---

## Axis 2 — Solve ONE problem, uniquely (the moat)

**Stop pitching "sentiment dashboard"** — loses to Brandwatch on polish. Reposition:

> **Misinformation & influence-ops radar that reads what DOM scrapers can't.**

Three assets nobody at the table copies in a weekend:
1. **Vision-OCR of Facebook** — reads the rendered meme / screenshot-of-screenshot. DOM scrapers + official APIs are blind here. Misinformation lives exactly here. (`connectors/facebook.py:_ocr`, `OCR_PROMPT`)
2. **Agentic convergence math** — entropy + saturation auto-explore to coverage. (`lib/cluster.py`, already shipped)
3. **You compute the astroturf signal then DELETE it.** `lib/dedup.py:near_dupe_keep` finds near-identical posts and drops them. Near-identical text + many distinct accounts + tight window = a coordinated campaign. **Stop deleting the evidence — surface it.**

**Build (ranked):**

| Feature | What | Reuses | Effort |
|---------|------|--------|--------|
| **S1 Coordination Radar** ★ cheapest blockbuster | group SimHash neighbors; ≥N distinct authors ⇒ flag. "⚠ 14 near-identical posts across 9 accounts" + bipartite author↔post graph | `dedup.py`, author field, Cytoscape | ~1d |
| **Flagship: Patient Zero** (narrative provenance) | trace a claim to its earliest appearance and forward through every mutation; spread tree blooms, FB root screenshot = evidence | new `lib/claims.py`, `embed.py`, `rag.py`, Cytoscape | ~5d |
| **S4 Multimodal flag** | Gemini Vision flags `meme / screenshot-of-article / out-of-context-image / text-on-image`; extract image-borne claims | extend `OCR_PROMPT` + one classifier field | ~1d |

Unique sentence no other team can say: *"Misinformation starts as a meme on Facebook no scraper can read. Watch us read it and trace it."*

---

## Axis 3 — Latest technology (technical depth)

Already strong — surface it louder, don't let it read as a wrapper.

- **Agentic loop** with entropy + saturation convergence (`cluster.py`) — research-flavored, not a prompt.
- **Multimodal Vision-OCR** — latest Gemini Flash vision; latest Claude (Opus 4.8 / Sonnet 4.6) for reasoning stages.
- **Graph-RAG + FAISS** cited Q&A (`rag.py`).
- **8-provider cascade** (`lib/dispatch.py`) — wire end-to-end (Groq + OpenRouter), proves "no single-vendor lock" is demonstrable, not aspirational.
- **Matryoshka embeddings** (opt #7) — 768-dim for clustering, full dim for RAG. Cheap flex, shows command of the embedding frontier.
- Optional: **MCP server** exposing PulseTrace as a tool — real interop, buzzword judges reward.

Pitch line: *"agentic, vision-native, provider-agnostic — convergence math + Graph-RAG, not a ChatGPT wrapper."*

---

## Axis 4 — Business: how it earns (ties to Axis 2 + 3)

**Value metric = per-run.** You already meter LLM calls / tokens / $ (§11.3 in features_plan). BYOK = user brings the key; you charge for orchestration + storage + the provenance/coordination intelligence layer.

**Tiers:**
| Tier | What | Drives |
|------|------|--------|
| **Open-source core** | self-host, BYOK, unlimited | GitHub stars; HN / r/LocalLLaMA launch = top of funnel |
| **Hosted** | $X/run or monthly bucket. saved-run library, share links, scheduled topic watches | revenue |
| **Team / Newsroom** | seats, audit trail, private connectors, **alerts on coordination/narrative spikes** | high willingness-to-pay |

**ICP (sharp wedge, not marketers):** small/mid newsrooms + fact-checking desks + election-integrity NGOs. They have the provenance pain, no Brandwatch budget, and high narrative value as design partners. Secondary: brand trust-&-safety + platform-policy teams.

**Revenue-driving features to build:**
1. **Per-run cost meter in UI** ("full topic ~2 cents") — value metric visible = billing justification. `run.json.metrics.cost`.
2. **`/runs` registry + share link** `/r/<run_id>` — saved library + judges replay after the pitch = retention proxy.
3. **Scheduled topic watch + Slack/email alert** on coordination spike — recurring-revenue hook. (Primitives exist: `/loop`, `/schedule`.)
4. **Briefing PDF export** (done, `briefing.py`) — "newsroom-ready in one click."

Beats incumbents: open-source + agentic + vision-native + **100× cheaper to start** vs Brandwatch ($50k+/yr, closed, no agent loop, can't read FB's rendered DOM).

---

## Build order (hits all four axes at once, ~1 week)

1. **Day 0–1 enablers:** FB OCR timestamp + permalink extraction (§3.6 — unlocks ALL time features) · `/runs` registry + cost meter · debug-off in prod.
2. **Day 1–2 cheap wow:** Coordination Radar (S1) · Glass-box agent (S2) · stage-stepper UI + source-health strip.
3. **Day 2–6 flagship:** Patient Zero provenance + evidence-first tabs.
4. **Day 6–7 close:** contradiction cards · share links · dark mode · cost/usage line · demo script + recorded fixture fallback.

Front-loads reliability and cheap wow, de-risks the flagship, makes the product genuinely usable.

---

## First move

**S1 Coordination Radar** — ~1 day, reuses `dedup.py` (the evidence currently thrown away), election-integrity story, FB-native. Biggest wow-per-LoC. Start here.

## Won't build (scope discipline)

Kafka / real-time streaming ingestion (batch loop + SSE bus is enough; `asyncio.Queue` covers the "streaming feel" in-process) · auth / multi-tenant · Docker / hosted infra beyond the demo box · SPA rewrite (extend `index.html`) · predictive trend modeling (can't fake credibly in a week).
