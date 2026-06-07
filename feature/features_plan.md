# PulseTrace — Killer Feature Plan (first-prize edition)

> Author: PM pass over the full codebase (2026-06-04).
> Inputs: judging rewards *all* axes (AI depth + demo wow + real-world impact + business); ~1 week build budget; **Facebook is the star** (fresh cookies at demo); deliverable = flagship + supporting cast + ranked portfolio.
>
> **Companion:** deep AI features (prompt-first, build-ready) + target-architecture redesign live in [`ai_deep_features.md`](./ai_deep_features.md) — read it for War-Room debate, Reflexion agent, claim verification, Graph-RAG, semantic-map cartography, confidence calibration, and the staged-pipeline refactor.

---

## 0. TL;DR — the bet

Stop pitching "another social-listening dashboard" (you lose to Brandwatch on polish and to every other team on novelty). Pitch the **one thing your moat makes possible that nobody else can copy in a weekend**:

> **PulseTrace is the open-source misinformation & influence-operations radar that reads what DOM scrapers can't — and traces how a narrative is born, mutates, and gets coordinated across the open web.**

Your unfair advantages, ranked:
1. **Vision-OCR of Facebook** — you ingest the rendered post (text *and* image/meme/screenshot-of-screenshot). DOM scrapers and official APIs cannot see this. Misinformation lives exactly here.
2. **Agentic loop with convergence math** (entropy + saturation in `lib/cluster.py`) — you already auto-explore a topic to coverage.
3. **You already compute the misinfo signal and delete it.** `lib/dedup.py:near_dupe_keep` finds near-identical posts and *drops* them. Near-identical text posted by many accounts in a tight window **is** astroturf. Stop deleting the evidence — surface it.

The flagship below turns those three assets into a single, unforgettable demo moment.

---

## 1. The winning thesis (repositioning)

| Old framing | First-prize framing |
|---|---|
| "Sentiment intelligence platform" | "Misinformation & influence-ops radar for the open web" |
| Output: charts + Q&A | Output: **provenance** (where a claim came from) + **coordination** (who is pushing it together) + **evidence** (the actual screenshots) |
| Competes with Brandwatch (loses) | Competes with nobody at the hackathon; adjacent to trust & safety / newsroom OSINT (a real, fundable category) |
| Buyer: marketer | Buyer: **newsroom, election-integrity team, brand trust & safety, platform policy** — higher willingness to pay, better story |

This reframe costs zero engine rewrites. Every primitive already exists. You are re-aiming, not rebuilding.

---

## 2. Assets the plan stands on (so every feature is feasible)

| Capability | Where it lives | Reused by |
|---|---|---|
| Multi-source fetch + agent loop | `lib/agent.py:run_agent` | everything |
| FB rendered-post OCR (text + image desc) | `lib/connectors/facebook.py:_ocr` (`OCR_PROMPT`) | flagship, multimodal |
| Embeddings (cached) | `lib/embed.py:embed_texts` | provenance, coordination |
| Clusters + centroids + entropy + saturation | `lib/cluster.py` | coordination, drift |
| Near-dup detector (SimHash/Hamming) | `lib/dedup.py:near_dupe_keep` | **coordination radar (the signal)** |
| Per-cluster stance, influence | `lib/stance.py`, `lib/influence.py` | scoring |
| FAISS RAG + cited screenshots | `lib/rag.py:ask` | interview-the-crowd, fact-check |
| Live event bus (SSE) | `lib/events.py:BUS`, `server.py:/events` | glass-box agent, live anything |
| HTML+PDF briefing w/ SVG charts | `lib/briefing.py` | provenance report export |
| Cytoscape graph render | `templates/index.html`, `server.py:/graph` | spread tree, author graph |

---

## 3. FLAGSHIP — "Patient Zero": Narrative Provenance Engine

**One-line:** Pick any claim in the corpus and watch PulseTrace trace it back to its earliest appearance and forward through every mutation, across Facebook, Reddit and HN, with the original screenshots as evidence.

### 3.1 Why this wins
- **Wow:** a live, animated spread tree of a rumor mutating ("original → reframed on Reddit → distorted on FB") is the kind of 20-second moment judges retell to other judges.
- **AI depth:** this is not clustering. It's atomic-claim extraction + cross-document directional entailment + temporal/source ordering + graph construction. Research-flavored, hard to fake.
- **Impact:** narrative provenance is the core unsolved problem in fact-checking and election integrity.
- **Business:** newsrooms and trust-&-safety teams pay for exactly this. It's the feature that makes the "$4B social-listening, none agentic" slide land.
- **Moat:** the origin is usually a Facebook image/meme that only your vision-OCR can read.

### 3.2 The demo moment (what the judge sees)
1. Run a topic (e.g. a contested local political claim).
2. Pipeline animates as today.
3. New panel: **Claims** list, ranked by spread. Click the top claim.
4. A Cytoscape tree blooms: root node = earliest post (with thumbnail), child nodes = mutations, edges labeled `verbatim / embellished / reframed / contradicted`. Nodes colored by source (FB blue, Reddit orange, HN grey), sized by reach.
5. Hover a node → the actual screenshot + author + engagement. Click "Why this edge?" → the LLM's one-line justification with both quotes.

### 3.3 How it works (pipeline)
Insert one new stage after labeling, before briefing, in `lib/agent.py`:

```
posts → [extract atomic claims] → [embed claims] → [group claim variants]
      → [order variants by time/source/specificity] → [classify directed edges]
      → claims.json + provenance graph → events + briefing section
```

1. **Claim extraction** (`lib/claims.py:extract_claims`). For each high-influence post (cap ~120 to bound cost), one batched LLM call returns 0–3 atomic, checkable claims. Atomic = single subject+predicate, no rhetoric.
2. **Variant grouping.** Embed each claim (reuse `embed_texts`, cache hits are free). A claim B is a *variant* of A if cosine ≥ 0.82. Union-find into variant groups. Each group = one "narrative."
3. **Ordering signal** (honest, multi-cue — see §3.6 on the timestamp problem):
   - real `ts` where available (Reddit/HN are accurate),
   - **new:** FB relative timestamp parsed from OCR ("3h", "Yesterday") → approx absolute,
   - specificity score (derived claims add names/numbers/quotes — LLM rates 0–1),
   - capture/iteration order as a weak tiebreak.
4. **Directed edges** (`lib/claims.py:classify_edge`). For adjacent variants in a group, one LLM call returns `{relation: verbatim|embellished|reframed|contradicted|unrelated, direction, why}`. Root = earliest, highest-generality node.
5. **Persist + emit.** `claims.json` per run; `BUS.publish(run_id, {"type":"provenance", ...})` so the tree streams in live; a provenance page in the briefing PDF.

### 3.4 LLM contracts (all via `lib/llm.py:chat_json`, strict JSON)
```text
EXTRACT_SYS:
"Extract 0-3 atomic, checkable factual claims from each post. Atomic = one
 subject + one predicate, no opinion words. Output JSON:
 {"items":[{"i":<post_index>,"claims":["..."]}]}"

EDGE_SYS:
"Two claims about the same topic. Decide how the SECOND relates to the FIRST.
 relation in [verbatim, embellished, reframed, contradicted, unrelated].
 Output JSON: {"relation":"...","derived_is_second":true|false,
 "why":"<=20 words quoting both"}"
```
Temperature 0.2, `max_tokens` capped, batched like `lib/stance.py:score_mixed`. Cost target: < $0.03/run on Gemini Flash.

### 3.5 Data model additions
```python
Claim = {
  "id": str,                 # "claim:<hash>"
  "text": str,
  "post_id": str,            # source post
  "group": int,              # variant group / narrative id
  "ts": int, "ts_approx": bool,
  "specificity": float,
  "influence": float,        # inherited from source post
}
ProvenanceEdge = {"src": claim_id, "dst": claim_id, "relation": str, "why": str}
```
Stored as `data/runs/<id>/claims.json`. No schema migration — additive.

### 3.6 The one real constraint, handled honestly
FB-OCR posts currently get `ts=int(time.time())` and `url=None` (`connectors/facebook.py:_shots_to_posts`). Pure-time ordering would be wrong for FB. Mitigations, in order of payoff:
- **Add timestamp + permalink hints to `OCR_PROMPT`** — Gemini can read the "3h / Yesterday / 12 May" string and often the post URL on the card. ~3 lines in the prompt, parse to relative seconds. This single upgrade unlocks *every* time-series feature in this doc (S-list + drift), so do it first.
- Fall back to specificity + entailment direction when timestamps tie or are absent. Provenance direction does not depend on time alone.
- Label approximate edges in the UI (dotted) so you never overclaim — judges reward intellectual honesty.

### 3.7 Build plan (~1 week, one concern per commit per `coding-standards.md`)
- **Day 1:** `lib/claims.py:extract_claims` + tests (TDD, mocked LLM) on a fixture run in `test_artifacts/`.
- **Day 2:** variant grouping (embeddings + union-find) + `lib/claims.py` ordering; unit tests with synthetic embeddings (mirror `tests/test_cluster.py`).
- **Day 3:** `classify_edge` + graph assembly → `claims.json`; wire into `agent.py` behind a flag (`PT_PROVENANCE=1`) so it can't break the core run.
- **Day 4:** `/provenance?run_id=` endpoint + SSE `provenance` event; OCR timestamp upgrade (§3.6).
- **Day 5:** Cytoscape spread-tree UI (reuse the `/graph` render path), node thumbnails, edge tooltips.
- **Day 6:** provenance section in `lib/briefing.py` PDF; polish, empty-state, "approximate" styling.
- **Day 7:** demo script, fixture run recorded as fallback, judge Q&A prep.

### 3.8 Risks
| Risk | Mitigation |
|---|---|
| Edge classification noisy on thin corpora | Only build trees for variant groups with ≥3 members; hide singletons |
| Extra LLM cost/latency | Cap to top-N influential posts; batch; run stage async after `done` event so the core demo never waits |
| FB timestamps unreadable | Fall back to specificity ordering; mark approximate |
| Whole feature flakes live | `PT_PROVENANCE` flag + recorded fixture run as backup |

---

## 4. Supporting cast (each ships independently in 0.5–1.5 days)

### S1 — Coordination / Astroturf Radar ★ (build this second; cheapest blockbuster)
**Insight:** you already compute near-dupes in `lib/dedup.py:near_dupe_keep` and **throw them away**. Keep them. A burst of near-identical posts (Hamming ≤ threshold) authored by *different* accounts in a tight window = a coordinated campaign.
- **Algorithm:** group posts by SimHash neighborhood; for each group with ≥N distinct authors, flag. Score = distinct_authors × copies × time-tightness. One optional LLM call: "are these organic or talking-points?"
- **UI:** "⚠ Coordinated campaign detected: 14 near-identical posts across 9 accounts" + bipartite author↔post graph (reuse Cytoscape).
- **Why it wins:** election-integrity story, near-zero new code, FB-native (astroturf lives on FB).
- **Effort:** ~1 day. **Reuses:** `dedup.py`, author field, Cytoscape.

### S2 — Glass-box Agent (live reasoning trace + self-critique)
Make the agent *think out loud* on screen. You already stream `seeded / iter_start / clustered / saturation / labeled` via `BUS`. Add a human-readable rationale to each decision ("coverage at 0.61 entropy; 'economic angle' under-covered → expanding with 2 queries") and a self-critique pass before stopping ("am I missing a counter-narrative? gap found → one more iter").
- **Why it wins:** pure AI-depth signal; turns invisible orchestration into a visible "agent brain" panel. Judges love seeing the loop reason.
- **Effort:** ~1 day. **Reuses:** `events.py`, `agent.py` decision points, `_llm_next`.

### S3 — Interview the Crowd (RAG-grounded persona focus group)
Generate one persona per major cluster, each speaking *only* from its members' posts via `lib/rag.py`. User asks a question → personas answer in-voice **with citations**, then a moderator agent synthesizes consensus vs. fault lines.
- **Why it wins:** demo wow + AI depth, and every word is grounded/cited (not LLM theater). Elevates the planned "ask the crowd."
- **Effort:** ~1.5 days. **Reuses:** FAISS index, cluster members, `chat_json`.

### S4 — Multimodal claim & manipulation flag (pure FB-moat play)
Your OCR already returns an image description for image-only posts. Push further: from the screenshot, have Gemini Vision flag `meme / screenshot-of-article / out-of-context-image / text-on-image claim`, and extract image-borne claims into the provenance engine.
- **Why it wins:** showcases the vision moat directly; "we read the meme, not just the caption" is a unique sentence no other team can say.
- **Effort:** ~1 day (extend `OCR_PROMPT` + one classifier field). **Reuses:** `connectors/facebook.py`.

### S5 — Contradiction / disputed-claim cards
Per narrative group (free once provenance exists), surface the strongest opposing pair: "⚠ Disputed — A claims X; B claims ¬X," each cited. Drop into the briefing.
- **Effort:** ~0.5 day on top of flagship. **Reuses:** provenance edges where `relation=contradicted`.

---

## 5. Cheap polish wins (do during dead time, ranked)
1. **FB OCR timestamp + permalink extraction** (§3.6) — unlocks all time features; do regardless.
2. **Stance-over-time stacked area** (`Chart.js` already loaded; x=iter, y=pos/neu/neg) — trivial once timestamps land.
3. **Shareable run link** — `data/runs/<id>` → tarball + signed `/r/<id>` read-only view. Lets judges replay after the pitch.
4. **Word cloud per cluster** (top TF-IDF terms) — 30 min, fills empty UI space.
5. **Dark mode** (CSS vars) — pure aesthetics, cheap credibility.
6. **Replay scrubber** — iter slider rewinds the dashboard from persisted per-iter state.

---

## 6. Ranked portfolio (impact × effort)

| # | Feature | Judge axis | Effort | Risk | Build? |
|---|---|---|---|---|---|
| F | Narrative Provenance ("Patient Zero") | depth+wow+impact+biz | ~5d | med | **Flagship** |
| S1 | Coordination / Astroturf Radar | impact+wow | ~1d | low | **Yes, 2nd** |
| S2 | Glass-box Agent reasoning | depth+wow | ~1d | low | **Yes** |
| 5.1 | FB OCR timestamp extraction | enabler | ~0.25d | low | **Yes, 1st** |
| S3 | Interview the Crowd personas | wow+depth | ~1.5d | med | If time |
| S4 | Multimodal meme/manipulation flag | moat+depth | ~1d | med | If time |
| S5 | Contradiction cards | impact | ~0.5d | low | Free w/ F |
| 5.2 | Stance-over-time chart | wow | ~0.5d | low | Nice-to-have |
| 5.3 | Shareable run link | biz | ~0.5d | low | Nice-to-have |
| — | Echo-chamber author map | depth | ~1d | med | Backlog |
| — | Cross-source "verified by N sources" badge | impact | ~0.5d | low | Backlog (good, lower wow) |
| — | One-click counter-narrative draft | impact | ~0.5d | med | Backlog (ethics caveat) |
| — | Account authenticity / bot score | impact | ~1d | high | Backlog (data-thin on FB) |

---

## 7. Engine upgrades that unlock the above (small, high-leverage)
- **`OCR_PROMPT` += timestamp + permalink + media-type fields** → real FB time + URLs + multimodal flag. One change, three features.
- **Author normalization** → dedupe "Page Name" vs "page name" so coordination/echo-chamber graphs are accurate.
- **`claims.json` as a first-class artifact** alongside `posts/clusters/run.json` → keeps provenance, contradictions, and the briefing in sync; survives replay/share.
- **Per-iter snapshots** (`clusters_iter_<n>.json`) → enables replay scrubber and drift Sankey for free.

---

## 8. Demo script (3 minutes — judges score the demo, not the repo)
1. **0:00 Hook (spoken):** "Misinformation doesn't start as text — it starts as a meme on Facebook that no scraper can read. Watch us read it and trace it." 
2. **0:20** Type a live contested topic, hit Run. Glass-box agent panel (S2) narrates the loop as the pipeline animates.
3. **1:10** Coordination Radar fires: "⚠ 14 near-identical posts, 9 accounts." Show the author↔post ring.
4. **1:40** Open **Patient Zero**: click top claim → spread tree blooms. Hover the FB root → the screenshot. "This is the origin; here's how it mutated on Reddit."
5. **2:30** Download the briefing PDF with the provenance + contradiction section. "Newsroom-ready in one click."
6. **2:50** One business line: "Open-source core, hosted per-run, built for trust & safety teams."

**Backup:** recorded fixture run (`test_artifacts/`) wired behind a `?demo=` flag so a dead cookie can't kill the pitch.

**Judge Q&A prep:** have answers ready for (a) "how do you order FB posts without timestamps?" → §3.6; (b) "how is this different from Brandwatch?" → vision-OCR moat + agentic + open-source + provenance; (c) "hallucination?" → every node/edge cites a real post + screenshot.

---

## 9. Won't build (YAGNI — cutting scope is a feature)
- Auth / accounts / multi-tenant — out of hackathon scope, kills time.
- Real-time streaming ingestion (Kafka) — batch loop is enough for the demo.
- Instagram/X polish — fragile, low ROI; keep as "wired, awaiting creds."
- Predictive trend modeling — too much to do credibly in a week; don't fake it.
- A second dashboard framework / SPA rewrite — extend `index.html`, don't restart.

---

## 10. Honesty / ethics notes (state these proactively — it builds trust with judges)
- FB scraping is fragile and ToS-adjacent; you already scope it as user-driven with their own cookies. Keep that framing.
- Provenance/coordination outputs are **leads, not verdicts** — label approximate edges, show evidence, never auto-publish a "bot" verdict.
- "Counter-narrative draft" (backlog) is dual-use; gate it as a journalist aid with citations, not an auto-poster.

---

## 11. SWE / engineering angle (the stuff that makes it *real*, and that technical judges quietly score)

A killer demo on a brittle backend loses to a slightly-less-flashy demo that never crashes. Harden these; several are also user-visible features.

### 11.1 Reliability & graceful degradation
- **Per-connector circuit breaker + status surface.** Each connector already fails soft in `agent.py` (`try/except continue`). Promote that to a visible "source health" strip: `reddit ✅  hn ✅  facebook ⚠ cookies stale`. Turns silent failure into a trust signal. (Reuses `lib/fb_cookies.py:status`.)
- **FB single-flight lock.** Only one Playwright Chromium should run at a time (anti-bot + RAM). Add a process-level lock around `FacebookConnector.fetch_many` so concurrent runs queue instead of trampling each other.
- **Run as a state machine with a `status` field** (`queued → fetching → clustering → labeling → done → error`) persisted in `run.json`. Enables resume, the replay scrubber, and an honest UI.

### 11.2 Persistence & run registry (unlocks product + business)
- **`/runs` endpoint + `data/runs/index.json`** listing every run (topic, time, counts, status). This single endpoint unlocks the *Saved Runs library*, share links, and the dashboard history rail — all "planned" features collapse into one small change.
- **Cross-run embed cache → SQLite.** `embed.py` caches per-run; persist `sha1(text) → vector` globally (`optimization_plan.md #3`). Repeat/overlapping topics cost zero embed tokens — a real cost lever for the hosted tier.
- **Atomic writes** for `store.write_json` (write-temp-then-rename) so a crash mid-run never leaves a half-written `clusters.json` that breaks the briefing.

### 11.3 Observability & cost metering (also a *business* asset)
- **Per-run usage meter:** count LLM calls, tokens, and an estimated `$` per stage; write to `run.json.metrics.cost`. Show it in the UI ("this run: 42 LLM calls · ~$0.02"). Judges love cost-awareness; it's also the value metric for per-run billing.
- **Structured logging with a `run_id` correlation field** instead of `print`. One JSON log line per stage → greppable, demo-debuggable.
- **`/healthz` + `/readyz`** (provider key present? cookies fresh? FAISS importable?) for the deployed demo and any uptime check.

### 11.4 Security / prod-readiness (cheap, prevents an embarrassing failure)
- **Turn off `debug=True` in production** (`server.py` runs Werkzeug debug + reloader off but debug on — the debugger PIN/console is a remote-code risk on a public box). Gate behind `FLASK_DEBUG` env.
- **Path-traversal hardening** is partially done in `/shots`; apply the same guard to any new `/runs/<id>` reads.
- **Basic rate limit** on `/run` and `/ask` (per-IP token bucket) so a curious judge or bot can't spin up 50 Playwright sessions.
- **BYOK key hygiene:** keys are injected per-request then restored (`_byok_apply/_byok_restore`) — good. Add: never log them, scrub from error payloads, and set them only in the run thread's env (document the single-worker assumption).

### 11.5 Dev-ex & quality (signals seriousness in the repo review)
- **CI: GitHub Actions** running `pytest` (mocked, the default suite — 43 tests already green) on every PR. A green badge in the README is free credibility.
- **`ruff` + `mypy` (lib/ only) + pre-commit** — matches `coding-standards.md` (type hints, narrow excepts). Catches the bare-except / missing-annotation drift.
- **Wire the 8-provider cascade end-to-end**, not just Gemini in the BYOK UI. The infra exists (`lib/dispatch.py`); enabling even Groq + OpenRouter makes the "no single-vendor dependence" claim demonstrable, not aspirational.
- **One-command demo:** `make demo` → seeds a cached fixture run so the app is never empty on first load.

---

## 12. Business perspective (turn the demo into a fundable story)

### 12.1 Wedge & ICP
Don't sell "social listening" to marketers (red ocean, you lose on polish). Land on a sharp wedge:
- **Primary ICP:** small/mid newsrooms + fact-checking desks + election-integrity NGOs. They have the *misinformation provenance* pain, no budget for Brandwatch, and high narrative value as design partners.
- **Secondary:** brand trust-&-safety and platform-policy teams who need to detect coordinated campaigns against a brand/topic.

### 12.2 Value metric & pricing (matches the architecture)
- **Value metric = per-run** (you already meter it in §11.3). Pricing maps cleanly to BYOK economics: the user brings their LLM key; you charge for orchestration + storage + the provenance/coordination intelligence layer.
- **Tiers:**
  - *Open-source core* — self-host, BYOK, unlimited. Drives adoption + GitHub stars (your real top-of-funnel; GTM is "launch on HN + r/LocalLLaMA").
  - *Hosted* — $X/run or a monthly bucket of runs; saved-run library, share links, scheduled topic watches.
  - *Team/Newsroom* — seats, audit trail, private connectors, retention, email/Slack alerts on narrative or coordination spikes.
- **Why this beats incumbents on the slide:** Brandwatch/Meltwater are closed, $50k+/yr, no agent loop, and can't read FB's rendered DOM. You're open-source, agentic, vision-native, and 100× cheaper to start.

### 12.3 Defensibility (what stops a fast-follower)
1. **Vision-OCR pipeline + prompt-tuning** for hostile DOMs — non-trivial to replicate well.
2. **Provenance/coordination dataset & graph** improves with usage (network effect on narratives).
3. **Provider-agnostic cascade** — you're not exposed to any single LLM vendor's pricing or outages.
4. **Open-source community** as moat + distribution.

### 12.4 Traction artifacts to show judges (you can generate these this week)
- A live counter (runs completed, sources live — already in `/docs`).
- One real, striking provenance case study (a rumor you actually traced) baked into the demo + README.
- Cost-per-run number from the meter ("full topic analysis for ~2 cents").
- A "design partner LOI / waitlist" link — even 10 signups is traction narrative.

### 12.5 Metrics that matter (instrument now, pitch later)
- Activation: % of first-time users who complete a run.
- Aha: % who open a provenance tree or download a briefing.
- Cost/run and time/run (you're already optimizing this — `perf` commits).
- Retention proxy: returning topics / saved runs.

### 12.6 Risk register (have answers ready)
| Risk | Framing for judges |
|---|---|
| Platform ToS / FB scraping | User-driven, their own cookies, public posts, leads-not-verdicts; pivot-ready to API sources |
| LLM hallucination | Every node/answer cites a real post + screenshot; approximate edges marked |
| Single-vendor LLM risk | 8-provider cascade with failover |
| "Is this just a wrapper?" | Provenance + coordination + convergence math + vision-OCR = defensible system, not a prompt |

---

## 13. UI/UX upgrade plan (make it *usable*, not just impressive)

Current state: a 4-view flow (landing → BYOK → app → shots) with Chart.js + Cytoscape + SSE log. It demos, but it's expert-only. Goal: a first-time judge succeeds in <30s and the moat (evidence + provenance) is front-and-center.

### 13.1 First-run & onboarding (kill the blank-canvas problem)
- **Sample-topic chips** under the input: "Try: [a trending claim] [a brand] [a policy debate]." One click = instant populated run. Never show an empty dashboard.
- **Three-step "how it works" ribbon** that doubles as the live progress stepper (see 13.2) — onboarding and status are the same component.
- **Progressive disclosure:** collapse Sources + BYOK behind an "Advanced" disclosure. Default = Reddit+HN+FB on, Gemini key from server. Most users should just type and go.

### 13.2 The run experience (this is the product)
- **Stage stepper with explicit states:** `Fetch → Cluster → Label → Stance → Provenance → Brief`, each showing pending/active/done/failed + live counts (posts found, clusters, $ spent). Reuses existing SSE events; just render them as a stepper, not a raw log.
- **Cancel button** + ETA. Long runs without a stop control feel broken.
- **Live source-health strip** (§11.1) so a stale FB cookie is visible, not a mystery hang. Tie the existing cookie-refresh modal to a one-click "Refresh now."
- **Skeleton loaders** for graph/briefing panels instead of empty boxes.

### 13.3 Results layout (tabs, evidence-first)
Replace the single scroll with tabs:
`Overview · Clusters · Patient Zero · Coordination · Ask · Briefing · Evidence`
- **Overview** = the exec summary + sentiment bars + top narratives + cost — the 10-second read.
- **Evidence** = a gallery of the FB screenshots (the moat) with author/engagement overlays. Lead with this; it's what no competitor has.
- **Patient Zero / Coordination** = the flagship visuals get their own room to breathe.

### 13.4 Q&A as a real chat surface
- Turn `/ask` into a streaming chat panel; **citation chips** in the answer (`[fb:…]`) are clickable and scroll-to / highlight the source card in the Evidence tab. Make the "cited evidence you can click and see" loop tactile — that's the trust moment.

### 13.5 Trust, clarity, honesty in the UI
- **Confidence/approximation labels** everywhere the model inferred something (approx timestamps = dotted edges; "lead, not verdict" badge on coordination/bot flags).
- **Plain-language microcopy.** Replace jargon ("entropy plateau") with human text ("coverage is leveling off — wrapping up").
- **Empty + error states with a next action** ("No FB posts — cookies may be stale. [Refresh]"), never a silent blank.

### 13.6 Shareability & polish
- **Read-only share link** (`/r/<run_id>`) so judges can reopen the run after your slot — and so it spreads. (Backed by the `/runs` registry, §11.2.)
- **Dark mode** via CSS variables (briefing already has a clean palette to borrow).
- **Toasts** for async events (cookie refreshed, briefing ready, run complete) instead of console-watching.

### 13.7 Accessibility & responsive (cheap credibility, sometimes scored)
- Keyboard-navigable controls, visible focus rings, `aria-label`s on the graph/stepper.
- Color contrast that passes AA; don't encode sentiment by color alone (add icons/labels — colorblind-safe).
- A responsive results view so a judge can open it on a phone mid-pitch.

### 13.8 Design-system hygiene (so it *feels* finished)
- Centralize tokens (spacing, color, radius, type scale) as CSS vars; reuse one card/button/badge component set across landing, app, briefing, and `/docs`. Consistency reads as "shipped product," not "hackathon project."

---

## 14. "Usable + hackathon-winning" definition of done
A judge, unprompted, can: (1) land → click a sample topic → see a run complete with live stages and cost; (2) open Patient Zero and click an FB screenshot as evidence; (3) ask one question and click a citation to its source; (4) download a briefing PDF; (5) reopen the run from a share link after the pitch — all without reading a manual, on desktop or phone, with nothing silently failing.

---

### Bottom line
Build order for the week, now spanning all four lenses:
1. **Enablers (Day 0–1):** FB OCR timestamp extraction · `/runs` registry + run state machine · per-run cost meter · debug-off + rate limit. *(SWE substrate that unlocks UX + business + features.)*
2. **Cheap wow (Day 1–2):** Coordination/Astroturf Radar · Glass-box Agent · stage-stepper UI + source-health strip.
3. **Flagship (Day 2–6):** Patient Zero narrative provenance + evidence-first tabs.
4. **Close (Day 6–7):** contradiction cards · share links · dark mode · cost/usage line · demo script + recorded fallback.

That sequence front-loads reliability and cheap wow, de-risks the flagship, makes the product genuinely usable, and gives you a demo that hits **every** judging axis — technical depth, demo wow, real-world impact, and a fundable business — with a story nobody else at the table can tell.
