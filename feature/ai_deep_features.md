# PulseTrace — Deep AI Features & Architecture (build-ready, prompt-first)

> Companion to `features_plan.md`. This doc is written to be *executed*: every feature carries its real system/user prompts, JSON contracts, pseudocode, data shapes, integration points, and an eval/guardrail block. Then a target-architecture redesign so the engine can carry all of it without `agent.py` turning into a 1000-line monster.
>
> Conventions: every LLM call goes through `lib/llm.py:chat_json` (strict JSON + retry, per `coding-standards.md`). Temp 0.2 unless noted. Cap `max_tokens`. Batch like `lib/stance.py:score_mixed`. All stages fail soft and emit on `lib/events.py:BUS`.

---

## How to read a feature block
```
WHAT/WHY · ARCHITECTURE · PROMPTS · ALGORITHM · DATA · INTEGRATION · EVAL/GUARDRAILS · EFFORT
```

---

## A1 — Multi-Agent Narrative War-Room (RAG-grounded debate + verdict)

**WHAT/WHY.** For a contested claim, spawn three role-conditioned agents — **Prosecutor** (argue it's false/misleading), **Defender** (argue true/supported), **Moderator/Judge** (weigh, rule, quantify uncertainty). Every argument must cite real retrieved posts; ungrounded assertions are disqualified by the judge. Output: a verdict with a calibrated confidence, the strongest evidence on each side, and the *remaining unknowns*. This is the most AI-deep, most watchable thing you can ship — a live courtroom over real data, not LLM theater, because the grounding is enforced.

**ARCHITECTURE.** New `lib/warroom.py`. Runs after provenance/claims exist. Retrieval per role via `lib/rag.py` (role-biased queries). Multi-round: N=2 rebuttal rounds, then judge. Streams each turn over `BUS` (`{"type":"warroom_turn", ...}`) so the UI animates it.

**PROMPTS.**
```text
ADVOCATE_SYS (instantiated per side):
"You are the {ROLE}. Claim under examination: \"{CLAIM}\".
 Argue ONLY the {SIDE} position. You may use ONLY the EVIDENCE posts below;
 every assertion must end with [post_id]. If evidence is insufficient, say
 'insufficient evidence' rather than inventing. Be concise (<=120 words).
 Output JSON: {\"argument\":\"...\",\"cited\":[\"post_id\",...],
 \"strongest_point\":\"...\"}"

REBUTTAL_SYS:
"You are the {ROLE}. Opponent argued: \"{OPP_ARGUMENT}\".
 Rebut using ONLY EVIDENCE below, citing [post_id] per point. Attack
 uncited or misread evidence explicitly. Output JSON:
 {\"rebuttal\":\"...\",\"cited\":[...],\"concedes\":\"...|none\"}"

JUDGE_SYS:
"You are an impartial analyst. Given the claim, both sides' cited arguments,
 and the evidence, rule. Discount any point whose [post_id] does not support
 it. Output JSON: {
   \"verdict\":\"supported|misleading|false|unverifiable\",
   \"confidence\":0.0-1.0,
   \"key_support\":[\"post_id\",...],
   \"key_refute\":[\"post_id\",...],
   \"open_questions\":[\"...\"],
   \"one_line\":\"<=25 words\"}"
```

**ALGORITHM.**
```
claim = pick_top_claim(run)                       # from claims.json
ev_pro  = rag.retrieve(claim, bias="support", k=8)
ev_con  = rag.retrieve(claim, bias="refute",  k=8)
pro  = advocate("Defender","supported", ev_pro)
con  = advocate("Prosecutor","false",   ev_con)
for r in range(2):
    con = rebut("Prosecutor", pro, ev_con); emit(con)
    pro = rebut("Defender",   con, ev_pro); emit(pro)
ruling = judge(claim, pro, con, ev_pro+ev_con)
verify_citations(ruling)                           # drop unresolved ids
```
Retrieval bias = append "evidence that the claim is true/false" to the query vector; cheap and effective.

**DATA.** `data/runs/<id>/warroom/<claim_id>.json` = `{claim, rounds:[...], ruling}`.

**INTEGRATION.** `/warroom?run_id=&claim_id=` (POST to start, SSE to stream); UI tab renders the back-and-forth as chat bubbles + a verdict gauge.

**EVAL/GUARDRAILS.** Citation-grounding check: each `cited` id must resolve in `posts.json` (reuse `rag._normalize_cite`); strip + penalize unresolved. Judge confidence calibrated via the self-consistency layer (A7). Never present verdict without `key_support`/`key_refute` evidence shown.

**EFFORT.** ~2 days. **Risk:** med (token cost — cap rounds at 2, claims at 1–3 per demo).

---

## A2 — Reflexion Coverage Agent (self-critiquing query expansion)

**WHAT/WHY.** Today `_llm_next` proposes follow-up queries from cluster labels. Upgrade it to a **reflexion loop**: the agent maintains a written self-assessment of coverage gaps across iterations, generates *counterfactual* queries ("what would someone who disagrees search?"), and only stops when its own critic agent signs off. This is the difference between "an LLM in a loop" and "an agent that reasons about its own blind spots" — exactly what AI-depth judges look for.

**ARCHITECTURE.** Replace `agent.py:_llm_next` with `lib/reflexion.py:next_step(ctx)`. Add a `coverage_memo` string to `RunContext`, appended each iter (this is the "reflexion memory"). Two calls: a **critic** (find gaps) then a **planner** (turn gaps into queries).

**PROMPTS.**
```text
CRITIC_SYS:
"You audit topic coverage. Given the topic, the clusters found, their stance
 mix, and the running coverage memo, identify what's MISSING: under-covered
 stances, missing stakeholders, absent counter-narratives, geographic/temporal
 gaps. Be specific and adversarial. Output JSON:
 {\"gaps\":[{\"kind\":\"stance|stakeholder|counter|geo|time\",
   \"desc\":\"...\",\"severity\":1-5}],
  \"coverage_score\":0.0-1.0,\"memo_addition\":\"<=40 words\"}"

PLANNER_SYS:
"Turn coverage gaps into <=3 search queries that would surface the MISSING
 material. Prefer counterfactual phrasing (search as the opposing camp would).
 Avoid repeating prior queries: {PRIOR_QUERIES}. Output JSON:
 {\"action\":\"expand|stop\",\"queries\":[\"...\"],\"why\":\"...\"}"
```

**ALGORITHM.**
```
critique = critic(topic, clusters, coverage_memo)
ctx.coverage_memo += critique.memo_addition
high_gaps = [g for g in critique.gaps if g.severity >= 3]
if not high_gaps or critique.coverage_score >= 0.85:
    return STOP                                  # principled stop, not just entropy
plan = planner(high_gaps, prior_queries)
return plan.queries (dedup vs fetched set)       # already tracked in agent.py
```
Keep the existing entropy/saturation guards as a hard floor; reflexion is the *smart* stop on top.

**DATA.** `run.json.coverage` = `{score, gaps, memo}` — also a great briefing section ("what we deliberately checked").

**INTEGRATION.** Drop-in for `_llm_next`; emit `{"type":"reflection", gaps, score}` so the Glass-box Agent panel (features_plan §S2) shows the agent *thinking about its own gaps*.

**EVAL/GUARDRAILS.** Hard cap `MAX_ITERS` stays. Dedupe queries against `fetched`. If critic returns malformed JSON, fall back to current `_llm_next`.

**EFFORT.** ~1 day. **Risk:** low.

---

## A3 — Cross-Source Claim Verification (NLI-style credibility meter)

**WHAT/WHY.** For each top claim, gather evidence across *all* sources, classify each evidence post as `supports / refutes / neutral` toward the claim (textual entailment), then aggregate into an **evidence-weighted veracity score** with a confidence interval. Weight evidence by source independence + influence + recency. Output a credibility meter ("Likely misleading — 71%, 9 refuting vs 3 supporting across 3 sources"). Deep because it's real evidence aggregation, not vibes; impactful because it's fact-checking.

**ARCHITECTURE.** `lib/verify.py`. Runs after claims (A-provenance) and RAG index exist. Per claim: retrieve k=12, NLI-classify in one batched call, aggregate with a transparent formula.

**PROMPTS.**
```text
NLI_SYS:
"For the CLAIM, label how each post relates to it.
 supports = post asserts the claim is true;
 refutes  = post asserts it is false/misleading;
 neutral  = related but doesn't adjudicate.
 Judge content, not tone. Output JSON:
 {\"items\":[{\"i\":<idx>,\"label\":\"supports|refutes|neutral\",
   \"confidence\":0.0-1.0,\"why\":\"<=12 words\"}]}"
```

**ALGORITHM (the aggregation is the interesting part — spell it out).**
```
for each evidence post e:
    w_e = log1p(influence(e)) * source_independence(e.source) * recency(e.ts)
S = Σ w_e for supports ;  R = Σ w_e for refutes
veracity = S / (S + R + ε)                        # 0=refuted .. 1=supported
strength = (S + R) / (S + R + N_neutral + ε)      # how adjudicated it is
n_sources = |distinct sources among non-neutral|
label = bucket(veracity) gated by strength & n_sources
        (require >=2 sources & strength>=0.4 else 'unverifiable')
```
`source_independence` down-weights many posts from the same source/author (coordination shouldn't inflate veracity — ties into the Astroturf Radar).

**DATA.** `claims.json[i].verdict = {veracity, strength, n_sources, support_ids, refute_ids}`.

**INTEGRATION.** Credibility meter on each claim card + in the briefing PDF; feeds the War-Room judge as a prior.

**EVAL/GUARDRAILS.** Self-consistency (A7) on the NLI batch for the top claim to get a real confidence. Always show the support/refute counts and source spread — never a bare number.

**EFFORT.** ~1.5 days. **Risk:** med (NLI noise — mitigate with confidence weighting + min-sources gate).

---

## A4 — Rhetoric & Manipulation-Technique Fingerprinting

**WHAT/WHY.** Go beyond pos/neu/neg. Per cluster (and per top post), detect **emotions** (anger, fear, pride, disgust, hope), **rhetorical/manipulation techniques** (whataboutism, strawman, fearmongering, ad hominem, false dilemma, loaded language, dog-whistle, cherry-picking), and a **toxicity/intensity** level. Render a "rhetoric profile" radar per narrative. This is dense, defensible NLP and it makes the misinfo story concrete ("this campaign runs on fear + whataboutism").

**ARCHITECTURE.** `lib/rhetoric.py`, batched like stance, one pass over cluster members. Slots beside `lib/stance.py` in the label stage.

**PROMPTS.**
```text
RHETORIC_SYS:
"Analyze persuasion mechanics of each post toward its theme. Choose only
 techniques actually present. techniques ⊂ {whataboutism, strawman,
 fearmongering, ad_hominem, false_dilemma, loaded_language, dog_whistle,
 cherry_picking, appeal_to_authority, none}. emotions ⊂ {anger, fear, pride,
 disgust, hope, sadness, neutral}. Output JSON:
 {\"items\":[{\"i\":<idx>,\"emotions\":[...],\"techniques\":[...],
   \"intensity\":0.0-1.0}]}"
```

**ALGORITHM.** Batched score → per-cluster aggregate = frequency vector over emotions+techniques (normalized) → radar chart inputs. Flag a cluster as "manipulation-heavy" if Σ technique-frequency > threshold.

**DATA.** `clusters.json[i].rhetoric = {emotions:{...}, techniques:{...}, intensity}`.

**INTEGRATION.** Radar (Chart.js polarArea) per cluster; "manipulation-heavy" badge feeds Coordination Radar + briefing.

**EVAL/GUARDRAILS.** Constrain to a closed label set (prevents hallucinated categories). `none` allowed so it doesn't over-label benign posts.

**EFFORT.** ~1 day. **Risk:** low–med.

---

## A5 — Graph-RAG (entity knowledge graph + community-aware retrieval)

**WHAT/WHY.** Flat top-k FAISS misses structure. Extract **entities** (people, orgs, places, claims) and **relations** from posts, build a knowledge graph, and retrieve over graph neighborhoods (entity → connected claims/posts), not just nearest vectors. Answers "who is connected to what" questions that flat RAG can't, and powers an interactive entity graph. GraphRAG is current-frontier and reads as serious AI work.

**ARCHITECTURE.** `lib/kg.py`: extraction → triples → `networkx` graph persisted as `kg.json`. Retrieval = hybrid (vector seed → expand 1–2 hops → rank). Augments `lib/rag.py:ask`.

**PROMPTS.**
```text
KG_EXTRACT_SYS:
"Extract entities and relations from each post. entity types: person, org,
 place, event, claim. relation = short verb phrase. Resolve obvious aliases.
 Output JSON: {\"items\":[{\"i\":<idx>,
   \"entities\":[{\"name\":\"...\",\"type\":\"...\"}],
   \"relations\":[{\"head\":\"...\",\"rel\":\"...\",\"tail\":\"...\"}]}]}"

GRAPH_ANSWER_SYS:
"Answer using the SUBGRAPH (entities, relations) and the cited posts only.
 Prefer multi-hop reasoning across relations. Cite [post_id]. Output JSON:
 {\"answer\":\"...\",\"path\":[\"A -rel-> B\",...],\"citations\":[...]}"
```

**ALGORITHM.**
```
triples = batched_extract(posts)                  # alias-merge by lowercased name
G = build_graph(triples)                           # nodes=entities, edges=relations
# retrieval:
seeds = entities_near(question)                    # vector match question→entity names
sub   = ego_graph(G, seeds, radius=2)
posts = posts_touching(sub) ranked by influence
answer = graph_answer(question, sub, posts[:8])
```

**DATA.** `kg.json` = `{nodes:[{id,name,type,degree}], edges:[{s,t,rel,posts:[id]}]}`.

**INTEGRATION.** Cytoscape entity graph tab; `/ask` gains a `mode=graph` toggle. Entities also enrich provenance (claims attach to entities).

**EVAL/GUARDRAILS.** Cap entities (merge by normalized name + embedding sim > 0.9 to fight alias explosion). Degrade to flat RAG if KG empty.

**EFFORT.** ~2 days. **Risk:** med (alias resolution is the hard part — keep heuristic).

---

## A6 — Narrative Cartography (animated semantic map)

**WHAT/WHY.** Project all post embeddings to 2D (UMAP, or PCA fallback — no new heavy dep beyond `umap-learn`, optional) and animate the map *filling in* across iterations: points appear, clusters form, stance colors them, the agent's new queries visibly explore empty regions. It's the single most beautiful way to show an agent *covering a space*. AI-native (it's literally the embedding manifold) and mesmerizing on screen.

**ARCHITECTURE.** `lib/cartography.py:project(embeddings) -> xy`. Compute per iteration (cheap on ≤500 pts), emit coords over `BUS`. Frontend renders on canvas/WebGL (deck.gl or plain canvas).

**ALGORITHM.** `umap.UMAP(n_neighbors=15, min_dist=0.1, metric="cosine")` → fit on iter-1, `transform` later iters for stable layout; fallback `sklearn.PCA(2)` if umap missing. Color = stance, size = influence, halo = cluster.

**DATA.** `data/runs/<id>/map_iter_<n>.json` = `[{id,x,y,cluster,stance,infl}]` (also powers the replay scrubber).

**INTEGRATION.** "Map" tab; new `{"type":"map", iter, points}` event. Doubles as the replay timeline.

**EVAL/GUARDRAILS.** Determinism via `random_state`; reuse iter-1 model with `transform` so points don't teleport between frames.

**EFFORT.** ~1.5 days (mostly frontend). **Risk:** low (PCA fallback guarantees it always renders).

---

## A7 — Confidence Calibration layer (cross-cutting, self-consistency)

**WHAT/WHY.** Wrap *any* judgment call (verdict, NLI, stance on a pivotal post) in **self-consistency**: sample the same prompt N=3–5 times at temp 0.5, take the majority answer, and report agreement-rate as a calibrated confidence. Cheap, model-agnostic, and it makes every number on screen *honest* — a maturity signal that separates first place from "cool demo."

**ARCHITECTURE.** `lib/confidence.py:vote(fn, n=5) -> (answer, confidence, dist)`. Apply selectively (expensive) to: War-Room verdict, top-claim NLI, coordination "organic vs campaign" call.

**ALGORITHM.**
```
samples = [fn() for _ in range(n)]                 # temp 0.5, same prompt
answer  = mode(samples); conf = count(answer)/n
return answer, conf, histogram(samples)
```

**INTEGRATION.** Confidence bars everywhere; dotted/greyed UI when conf < 0.6 (ties to UI honesty in `features_plan.md §13.5`).

**EFFORT.** ~0.5 day. **Risk:** low (gate by cost — only on the handful of pivotal calls).

---

## A8 — More to mine (one-liners, each genuinely deep)
- **Cross-lingual narrative tracking (Bangla⇄English).** Your FB target is BD politics. Multilingual embeddings already cluster across languages; add translate-on-read + a "same narrative, 2 languages" link. Unique, regionally credible, judge-memorable. ~1 day.
- **Predictive narrative momentum.** Features: engagement velocity, cross-source replication rate, polarization. Logistic/heuristic → "rising / peaking / fading" badge per narrative (needs the OCR-timestamp enabler). Calibrate, show the features, don't overclaim. ~1.5 days.
- **Synthetic AI-image suspicion.** Gemini Vision already sees the image; add a `likely_ai_generated` + `out_of_context` flag to `OCR_PROMPT`. Multimodal misinfo in one prompt field. ~0.5 day.
- **Active learning HITL.** User corrects a cluster label/stance → store the correction, re-bias the next iter's prompts with it. "It learns from you" in the demo. ~1 day.
- **Entity stance matrix.** entity × {pro/anti/neutral} heatmap from A5 entities + A3 stance. ~0.5 day.

---

# Architecture improvements (so the engine can actually carry the above)

The current `lib/agent.py:run_agent` is ~290 lines doing fetch + dedup + embed + cluster + label + stance + influence + persist + decide + briefing. That violates the repo's own rule (`coding-standards.md`: "small focused files, one responsibility"). Adding A1–A8 inline would make it unmaintainable. Refactor to a **staged pipeline** — incremental, behind flags, non-breaking.

## R1 — Pipeline + RunContext (the backbone change)
Introduce a `Stage` protocol and a `Pipeline` runner that threads a single mutable `RunContext` and checkpoints after each stage.

```python
# lib/context.py
@dataclass
class RunContext:
    run_id: str; topic: str; sources: list[str]; cfg: Settings
    posts: list[Post] = field(default_factory=list)
    emb: np.ndarray | None = None
    labels: np.ndarray | None = None
    clusters: list[dict] = field(default_factory=list)
    claims: list[dict] = field(default_factory=list)
    coverage_memo: str = ""
    metrics: dict = field(default_factory=dict)     # incl. cost meter
    bus: EventBus = BUS

# lib/pipeline.py
class Stage(Protocol):
    name: str
    def run(self, ctx: RunContext) -> None: ...

class Pipeline:
    def __init__(self, stages: list[Stage]): ...
    def run(self, ctx):
        for s in self.stages:
            ctx.bus.publish(ctx.run_id, {"type":"stage_start","stage":s.name})
            try: s.run(ctx)
            except StageError as e: ctx.bus.publish(...,"stage_error"); continue
            checkpoint(ctx, s.name)                  # atomic write
            ctx.bus.publish(ctx.run_id, {"type":"stage_done","stage":s.name})
```
Stages: `Fetch · Dedup · Embed · Cluster · Label · Stance · Rhetoric · Influence · Provenance · Coordination · Verify · Cartography · Brief`. Each is a small file. Adding a feature = adding a stage to a list. The agent loop becomes the *iteration controller* around the pipeline, not the kitchen sink.

**Migration:** wrap today's logic as stages one at a time; keep `run_agent` as a thin shim calling `Pipeline`. Tests stay green throughout.

## R2 — Event bus: persisted log + pluggable backend
Today `events.py:BUS` is in-memory and process-local. Two problems: (a) SSE reconnect loses all prior events (judge refreshes → blank), (b) can't scale past one worker.
- **Persist an append-only event log** per run (`events.jsonl`). `/events` replays the log on connect, then tails live. Reconnect-safe, and it *is* the replay timeline.
- **`EventBus` protocol** with `InMemoryBus` (default) and an optional `RedisBus` (pub/sub) for multi-worker. No code change at call sites.

## R3 — Store abstraction + run registry + atomicity
- `Store` protocol; `JSONStore` (current) + `SQLiteCache` for the global embed/LLM cache.
- **Atomic writes** (`tmp` + `os.replace`) so a crash never corrupts `clusters.json`.
- **`runs/index.json` registry** (append on start/finish) → powers `/runs`, saved-run library, share links (collapses 3 roadmap items into one).

## R4 — LLM layer hardening (`lib/llm/`)
- **Response cache** keyed by `sha1(model+system+user+max_tokens)` → repeat stages/topics cost zero. Huge for dev + demo reruns.
- **Cost/token meter** → `ctx.metrics.cost` (the business value metric + UI line).
- **Schema validation for LLM output** with small `pydantic` models (allowed by standards: validating external input). Replaces silent `_coerce_dict` guessing with typed parse + one structured retry on validation failure.
- **Centralized retry/backoff** (currently scattered). Keep the cascade in `dispatch.py`; wire it in prod (not just tests).

## R5 — Connector contract upgrade
- Add capability metadata to `Connector`: `supports_batch`, `has_timestamps`, `is_fragile`, `rate_limit`. The agent uses it to schedule (parallel vs serial), to weight `source_independence` (A3), and to render the source-health strip.
- **Normalization layer:** `normalize_author()` (case/whitespace/alias) and `normalize_ts()` (parse FB relative times from the new OCR field) so coordination/provenance/timeline math is correct.
- **Connector registry** via entry points → the "Connector SDK" roadmap item, basically free once contracts are explicit.

## R6 — Concurrency & runtime
- **FB single-flight lock** (only one Playwright at a time) — anti-bot + RAM safety.
- **Run executor**: today `threading.Thread(daemon=True)` per run. For >1 concurrent run, move to a small bounded `ThreadPool`/task queue with a `status` field per run (`queued/running/done/error`). Keeps the "no heavy infra" non-goal while preventing thrash.
- **Async unification (optional):** the FB connector does `asyncio.run` inside a thread. Longer term, a single async core (httpx.AsyncClient pooled — `optimization_plan.md #15`) removes per-call TLS setup across all Gemini calls.

## R7 — Config & observability
- **`lib/config.py:Settings`** dataclass loaded once from env (replaces scattered `os.environ.get` across modules). One place to see every knob.
- **Structured logging** with `run_id`/`stage` fields (replace `print` in connectors). One JSON line per stage → trivially greppable during a live demo.
- **`/healthz` + `/readyz`** (keys present, cookies fresh, faiss/umap importable).

## R8 — Embedding strategy (from `optimization_plan.md`, worth doing)
- **Matryoshka dual-dim:** 768-d for clustering (faster FAISS/RAM), full dim for the RAG index. Free quality/speed win.
- **Global cross-run embed cache** in SQLite (`sha1(text)->vec`). Overlapping topics = zero embed cost (the hosted-tier margin lever).

---

## Suggested build order (deep-AI track, layered on `features_plan.md`)
1. **R1 pipeline + R3 atomic store + R4 cost meter** — substrate; everything else plugs in cleanly.
2. **A2 Reflexion** + **A7 Confidence** — small, upgrade the agent's brain and make all numbers honest.
3. **A4 Rhetoric** + **A3 Verification** — dense NLP + credibility meter (impact).
4. **A1 War-Room** — the AI-deep centerpiece demo.
5. **A5 Graph-RAG** + **A6 Cartography** — if time; both are pure wow.
6. **R2 persisted events + R5 connector contracts** — reliability + reconnect-safe demo + Connector SDK.

Each item is independently shippable, fails soft, and sits behind a flag — so a half-finished deep feature can never sink the core demo. That is the hackathon-winning posture: ambitious AI on a backbone that does not break on stage.
