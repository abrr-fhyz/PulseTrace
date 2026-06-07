# Opinion-Aware Evidence Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opinion-aware evidence layer — a completed run is post-processed into `evidence.json` (exec summary, pro/con claims with hybrid confidence, community consensus, ranking), surfaced through new dashboard tabs; the agent biases its queries pro/con when an opinion is given.

**Architecture:** Pure scoring functions in `lib/evidence_score.py` (TDD). Orchestration + LLM extraction in `lib/evidence.py` producing `evidence.json`. `lib/agent.py` plumbs an optional `opinion`, biasing seed/expansion prompts and calling `evidence.build` at the end. `server.py` accepts `opinion` on `/run` and serves `GET /run/<id>/evidence`. `templates/index.html` gains an opinion input + tabbed views + Chart.js visualizations.

**Tech Stack:** Python 3.12, Flask + SSE, OpenAI SDK via `lib/llm.py:chat_json`, existing connectors/cluster/stance/influence, Chart.js (CDN).

**Design doc:** `.claude/plans/2026-06-07-opinion-evidence-dashboard.md`

---

## File Structure

- Create: `lib/evidence_score.py` — pure scoring/ranking math, no IO/LLM.
- Create: `lib/evidence.py` — `build(run_id, opinion)` → `evidence.json`.
- Create: `tests/test_evidence_score.py` — scoring math (TDD).
- Create: `tests/test_evidence.py` — `build()` with mocked LLM.
- Create: `tests/test_agent_opinion.py` — opinion-biased prompts.
- Modify: `lib/agent.py` — `opinion` param, biased prompts, call `evidence.build`.
- Modify: `server.py` — `/run` opinion field, `GET /run/<id>/evidence`.
- Modify: `templates/index.html` — opinion input, tabs, charts.

Reference data shapes:
- `clusters.json` item: `{id:int, label:str, desc:str, centroid:[float], members:[post_id], sentiment:{pos,neu,neg}, top_posts:[post_id]}`
- `posts.json` item = `Post.to_dict()`: `{id, source, text, author, url, ts, reactions, comments, shares, raw}`

---

## Task 1: Pure scoring — `lib/evidence_score.py`

**Files:**
- Create: `lib/evidence_score.py`
- Test: `tests/test_evidence_score.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_evidence_score.py
from __future__ import annotations
from lib.connectors.base import Post
from lib import evidence_score as es


def _post(pid, source, ts=0, reactions=0, comments=0, shares=0, text="hello world"):
    return Post(id=pid, source=source, text=text, ts=ts,
                reactions=reactions, comments=comments, shares=shares)


def test_engagement_sums_signals():
    posts = [_post("a", "reddit", reactions=2, comments=3, shares=1),
             _post("b", "hn", reactions=4)]
    assert es.engagement(posts) == 10


def test_source_diversity_counts_distinct():
    posts = [_post("a", "reddit"), _post("b", "reddit"), _post("c", "hn")]
    assert es.source_diversity(posts) == 2


def test_corroboration_norm_one_source_is_low():
    one = [_post("a", "reddit"), _post("b", "reddit")]
    multi = [_post("a", "reddit"), _post("b", "hn"), _post("c", "facebook")]
    assert es.corroboration(one) < es.corroboration(multi)
    assert 0.0 <= es.corroboration(one) <= 1.0
    assert 0.0 <= es.corroboration(multi) <= 1.0


def test_credibility_hn_beats_instagram():
    assert es.credibility([_post("a", "hn")]) > es.credibility([_post("b", "instagram")])


def test_sample_size_norm_bounds():
    assert es.sample_size_norm(0, 10) == 0.0
    assert es.sample_size_norm(10, 10) == 1.0
    assert es.sample_size_norm(5, 0) == 0.0


def test_recency_score_newer_is_higher():
    now = 1_000_000
    old = es.recency_score([_post("a", "hn", ts=now - 30 * 86400)], now)
    new = es.recency_score([_post("b", "hn", ts=now - 1)], now)
    assert new > old


def test_data_quality_rewards_longer_engaged_text():
    thin = [_post("a", "reddit", text="ok")]
    rich = [_post("b", "reddit", text="x" * 400, reactions=20)]
    assert es.data_quality(rich) > es.data_quality(thin)


def test_rank_returns_five_axes_in_unit_range():
    posts = [_post("a", "hn", ts=10, reactions=5, comments=2),
             _post("b", "reddit", ts=20, reactions=1)]
    r = es.rank(posts, max_members=2, now=100)
    assert set(r) == {"credibility", "data_quality", "sample_size", "recency", "corroboration"}
    assert all(0.0 <= v <= 1.0 for v in r.values())


def test_strength_bucket_thresholds():
    weak = {k: 0.1 for k in ("credibility", "data_quality", "sample_size", "recency", "corroboration")}
    strong = {k: 0.9 for k in weak}
    assert es.strength_bucket(weak) == "weak"
    assert es.strength_bucket(strong) == "strong"


def test_blend_is_weighted_and_bounded():
    assert es.blend(0.0, 0.0) == 0.0
    assert es.blend(1.0, 1.0) == 1.0
    mid = es.blend(1.0, 0.0)
    assert 0.0 < mid < 1.0


def test_empty_inputs_return_zeros_not_errors():
    assert es.engagement([]) == 0
    assert es.source_diversity([]) == 0
    assert es.corroboration([]) == 0.0
    r = es.rank([], max_members=0, now=0)
    assert all(v == 0.0 for v in r.values())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_evidence_score.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.evidence_score'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/evidence_score.py
"""Pure evidence-ranking math. No IO, no LLM."""
from __future__ import annotations
import math
from .connectors.base import Post
from .influence import recency as _recency

SOURCE_CREDIBILITY: dict[str, float] = {
    "hn": 0.8, "reddit": 0.6, "facebook": 0.5, "x": 0.5, "instagram": 0.4,
}
SOURCE_CATEGORY: dict[str, str] = {
    "hn": "forums", "reddit": "forums", "facebook": "social",
    "x": "social", "instagram": "social",
}
_RANK_WEIGHTS = ("credibility", "data_quality", "sample_size", "recency", "corroboration")
_COMPUTED_WEIGHT = 0.6
_LLM_WEIGHT = 0.4


def engagement(posts: list[Post]) -> int:
    return sum(p.reactions + p.comments + p.shares for p in posts)


def source_diversity(posts: list[Post]) -> int:
    return len({p.source for p in posts})


def corroboration(posts: list[Post]) -> float:
    n = source_diversity(posts)
    if n <= 0:
        return 0.0
    return min(1.0, (n - 1) / 3.0)


def credibility(posts: list[Post]) -> float:
    if not posts:
        return 0.0
    vals = [SOURCE_CREDIBILITY.get(p.source, 0.5) for p in posts]
    return sum(vals) / len(vals)


def sample_size_norm(n_members: int, max_members: int) -> float:
    if max_members <= 0 or n_members <= 0:
        return 0.0
    return min(1.0, n_members / max_members)


def recency_score(posts: list[Post], now: int) -> float:
    tss = [p.ts for p in posts if p.ts]
    if not tss:
        return 0.0
    return max(_recency(ts, now) for ts in tss)


def data_quality(posts: list[Post]) -> float:
    if not posts:
        return 0.0
    avg_len = sum(len(p.text or "") for p in posts) / len(posts)
    len_score = min(1.0, avg_len / 300.0)
    eng_score = min(1.0, math.log1p(engagement(posts)) / math.log1p(50))
    return 0.5 * len_score + 0.5 * eng_score


def rank(posts: list[Post], max_members: int, now: int) -> dict[str, float]:
    if not posts:
        return {k: 0.0 for k in _RANK_WEIGHTS}
    return {
        "credibility": credibility(posts),
        "data_quality": data_quality(posts),
        "sample_size": sample_size_norm(len(posts), max_members),
        "recency": recency_score(posts, now),
        "corroboration": corroboration(posts),
    }


def strength_bucket(ranking: dict[str, float]) -> str:
    if not ranking:
        return "weak"
    mean = sum(ranking.values()) / len(ranking)
    if mean >= 0.66:
        return "strong"
    if mean >= 0.33:
        return "moderate"
    return "weak"


def blend(computed_norm: float, llm_conf: float) -> float:
    v = _COMPUTED_WEIGHT * computed_norm + _LLM_WEIGHT * llm_conf
    return max(0.0, min(1.0, v))


def category_for(source: str) -> str:
    return SOURCE_CATEGORY.get(source, "social")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_evidence_score.py -v`
Expected: PASS (all 11 tests)

- [ ] **Step 5: Commit**

```bash
git add lib/evidence_score.py tests/test_evidence_score.py
git commit -m "feat(evidence): pure scoring + 5-axis ranking math"
```

---

## Task 2: Evidence builder — `lib/evidence.py`

**Files:**
- Create: `lib/evidence.py`
- Test: `tests/test_evidence.py`

LLM contract — `evidence.py` makes ONE `chat_json` call returning:
```jsonc
{
  "exec_summary": {"plain_topic","key_findings":[],"agreements":[],"disagreements":[],"conclusion"},
  "topic_overview": "...",
  "community_consensus": {"top_praise":[],"top_criticism":[],"misconceptions":[],"uncertainties":[]},
  "uncertainty": ["..."],
  "final_assessment": "...",
  "claims": [
     {"text","side":"pro|con|neutral","reasoning",
      "llm_confidence":0.0,"cluster_ids":[int]}
  ]
}
```
`evidence.py` then attaches computed `ranking`, `evidence_strength`, blended
`confidence`, and `source_categories` (from each claim's clusters) per claim,
and splits `screen_a`/`screen_b`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_evidence.py
from __future__ import annotations
import json
from unittest.mock import patch
from lib import evidence
from lib.store import run_dir, write_json


def _seed_run(tmp_root, run_id, with_posts=True):
    write_json(run_id, "run.json", {"id": run_id, "topic": "Elden Ring", "sources": ["reddit"]})
    write_json(run_id, "clusters.json", [
        {"id": 0, "label": "Combat praise", "desc": "loved", "centroid": [],
         "members": ["reddit:1", "reddit:2"], "sentiment": {"pos": 0.8, "neu": 0.1, "neg": 0.1},
         "top_posts": ["reddit:1"]},
        {"id": 1, "label": "Too hard", "desc": "difficulty", "centroid": [],
         "members": ["hn:3"], "sentiment": {"pos": 0.1, "neu": 0.2, "neg": 0.7},
         "top_posts": ["hn:3"]},
    ])
    write_json(run_id, "posts.json", [
        {"id": "reddit:1", "source": "reddit", "text": "combat is amazing", "ts": 100,
         "reactions": 10, "comments": 4, "shares": 1, "author": None, "url": None, "raw": {}},
        {"id": "reddit:2", "source": "reddit", "text": "bosses are fair", "ts": 90,
         "reactions": 5, "comments": 2, "shares": 0, "author": None, "url": None, "raw": {}},
        {"id": "hn:3", "source": "hn", "text": "way too punishing for newcomers", "ts": 80,
         "reactions": 8, "comments": 6, "shares": 0, "author": None, "url": None, "raw": {}},
    ])


_FAKE_LLM = {
    "exec_summary": {"plain_topic": "An action RPG.", "key_findings": ["loved combat"],
                     "agreements": ["combat depth"], "disagreements": ["difficulty"],
                     "conclusion": "Polarizing but acclaimed."},
    "topic_overview": "Open-world soulslike.",
    "community_consensus": {"top_praise": ["combat"], "top_criticism": ["difficulty"],
                            "misconceptions": ["no story"], "uncertainties": ["performance"]},
    "uncertainty": ["frame pacing on old GPUs"],
    "final_assessment": "Strong game; difficulty is a real barrier.",
    "claims": [
        {"text": "Combat is deep and rewarding", "side": "pro", "reasoning": "many praise it",
         "llm_confidence": 0.8, "cluster_ids": [0]},
        {"text": "Punishing difficulty deters newcomers", "side": "con",
         "reasoning": "repeated complaint", "llm_confidence": 0.6, "cluster_ids": [1]},
    ],
}


def test_build_writes_evidence_json_with_screens(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.store.ROOT", tmp_path / "runs")
    run_id = "t1"
    _seed_run(tmp_path, run_id)
    with patch("lib.evidence.chat_json", return_value=_FAKE_LLM):
        out = evidence.build(run_id, opinion="I want to play Elden Ring")

    assert out["opinion"] == "I want to play Elden Ring"
    assert len(out["claims"]) == 2
    pro = [c for c in out["claims"] if c["side"] == "pro"][0]
    assert 0.0 <= pro["confidence"] <= 1.0
    assert pro["evidence_strength"] in {"weak", "moderate", "strong"}
    assert set(pro["ranking"]) == {"credibility", "data_quality", "sample_size", "recency", "corroboration"}
    assert pro["source_categories"]  # non-empty
    assert len(out["screen_a"]) == 1 and len(out["screen_b"]) == 1
    assert out["exec_summary"]["plain_topic"]
    # persisted
    saved = json.loads((run_dir(run_id) / "evidence.json").read_text())
    assert saved["final_assessment"]


def test_build_neutral_when_no_opinion(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.store.ROOT", tmp_path / "runs")
    run_id = "t2"
    _seed_run(tmp_path, run_id)
    with patch("lib.evidence.chat_json", return_value=_FAKE_LLM):
        out = evidence.build(run_id, opinion=None)
    assert out["opinion"] is None
    assert out["screen_a"] == [] and out["screen_b"] == []


def test_build_survives_llm_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.store.ROOT", tmp_path / "runs")
    run_id = "t3"
    _seed_run(tmp_path, run_id)
    with patch("lib.evidence.chat_json", side_effect=RuntimeError("boom")):
        out = evidence.build(run_id, opinion="x")
    assert out["claims"] == []
    assert out["exec_summary"]["plain_topic"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_evidence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.evidence'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/evidence.py
"""Opinion-aware evidence layer: build evidence.json from a completed run."""
from __future__ import annotations
import logging
import time
from .connectors.base import Post
from .llm import chat_json
from .store import read_json, write_json
from . import evidence_score as es

_LOG = logging.getLogger("evidence")

_NEUTRAL = {
    "exec_summary": {"plain_topic": "", "key_findings": [], "agreements": [],
                     "disagreements": [], "conclusion": ""},
    "topic_overview": "",
    "community_consensus": {"top_praise": [], "top_criticism": [],
                            "misconceptions": [], "uncertainties": []},
    "uncertainty": [],
    "final_assessment": "",
    "claims": [],
}

_BEHAVIOR = (
    "Rules: never optimize for agreement with the user; seek the strongest "
    "evidence both for and against; distinguish facts, interpretations, and "
    "opinions; explicitly flag uncertainty and missing information; avoid false "
    "balance when evidence overwhelmingly favors one side; prefer evidence over "
    "popularity."
)
_SCHEMA = (
    'Output JSON: {"exec_summary":{"plain_topic":str,"key_findings":[str],'
    '"agreements":[str],"disagreements":[str],"conclusion":str},'
    '"topic_overview":str,"community_consensus":{"top_praise":[str],'
    '"top_criticism":[str],"misconceptions":[str],"uncertainties":[str]},'
    '"uncertainty":[str],"final_assessment":str,'
    '"claims":[{"text":str,"side":"pro"|"con"|"neutral","reasoning":str,'
    '"llm_confidence":number,"cluster_ids":[int]}]}'
)


def build(run_id: str, opinion: str | None) -> dict:
    clusters = read_json(run_id, "clusters.json") or []
    run = read_json(run_id, "run.json") or {}
    posts_raw = read_json(run_id, "posts.json") or []
    posts_by_id = {p["id"]: _to_post(p) for p in posts_raw}

    llm = _llm_analyze(run.get("topic", ""), opinion, clusters)
    now = int(time.time())
    max_members = max((len(c.get("members", [])) for c in clusters), default=0)
    members_by_cid = {int(c["id"]): [posts_by_id[m] for m in c.get("members", [])
                                     if m in posts_by_id] for c in clusters}

    claims = [_enrich_claim(c, members_by_cid, max_members, now)
              for c in llm.get("claims", [])]
    if opinion is None:
        for c in claims:
            c["side"] = "neutral"

    out = {
        "opinion": opinion,
        "exec_summary": llm.get("exec_summary", _NEUTRAL["exec_summary"]),
        "topic_overview": llm.get("topic_overview", ""),
        "community_consensus": llm.get("community_consensus", _NEUTRAL["community_consensus"]),
        "claims": claims,
        "screen_a": [c for c in claims if c["side"] == "pro"] if opinion else [],
        "screen_b": [c for c in claims if c["side"] == "con"] if opinion else [],
        "uncertainty": llm.get("uncertainty", []),
        "final_assessment": llm.get("final_assessment", ""),
    }
    write_json(run_id, "evidence.json", out)
    return out


def _enrich_claim(claim: dict, members_by_cid, max_members: int, now: int) -> dict:
    cids = [int(x) for x in claim.get("cluster_ids", []) if isinstance(x, (int, float))]
    posts: list[Post] = []
    for cid in cids:
        posts.extend(members_by_cid.get(cid, []))
    ranking = es.rank(posts, max_members, now)
    computed = sum(ranking.values()) / len(ranking) if ranking else 0.0
    llm_conf = _clamp(claim.get("llm_confidence", 0.0))
    cats = sorted({es.category_for(p.source) for p in posts}) or ["unknown"]
    return {
        "text": str(claim.get("text", "")),
        "side": claim.get("side", "neutral"),
        "confidence": es.blend(computed, llm_conf),
        "evidence_strength": es.strength_bucket(ranking),
        "reasoning": str(claim.get("reasoning", "")),
        "source_categories": cats,
        "cluster_ids": cids,
        "ranking": ranking,
    }


def _llm_analyze(topic: str, opinion: str | None, clusters: list[dict]) -> dict:
    labels = "\n".join(
        f'- cluster {c["id"]} "{c.get("label","")}" '
        f'(sentiment {c.get("sentiment",{})}, n={len(c.get("members",[]))}): {c.get("desc","")}'
        for c in clusters
    ) or "(no clusters)"
    stance = (
        f'The user holds this opinion: "{opinion}". Split claims into "pro" '
        "(supporting the opinion) and \"con\" (challenging it). Present the "
        "strongest arguments on each side."
        if opinion else
        "No user opinion. Produce a neutral analysis; tag all claims \"neutral\"."
    )
    system = (
        "You are an evidence analyst building a balanced, Community-Notes-style "
        "report from clustered social-media discussion. " + _BEHAVIOR + " " + _SCHEMA
    )
    user = f"Topic: {topic}\n{stance}\n\nCluster findings:\n{labels}"
    try:
        out = chat_json(system, user, max_tokens=1500, stage="evidence")
        if not isinstance(out, dict):
            raise ValueError("non-dict")
        return out
    except Exception as e:  # connector/LLM failure must not kill the run
        _LOG.warning("evidence LLM failed: %s", e)
        return dict(_NEUTRAL)


def _to_post(d: dict) -> Post:
    return Post(
        id=d.get("id", ""), source=d.get("source", ""), text=d.get("text", ""),
        author=d.get("author"), url=d.get("url"), ts=int(d.get("ts", 0) or 0),
        reactions=int(d.get("reactions", 0) or 0),
        comments=int(d.get("comments", 0) or 0),
        shares=int(d.get("shares", 0) or 0), raw=d.get("raw", {}) or {},
    )


def _clamp(v) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_evidence.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add lib/evidence.py tests/test_evidence.py
git commit -m "feat(evidence): build evidence.json (claims, screens, hybrid confidence)"
```

---

## Task 3: Agent opinion plumbing — `lib/agent.py`

**Files:**
- Modify: `lib/agent.py`
- Test: `tests/test_agent_opinion.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_opinion.py
from __future__ import annotations
from unittest.mock import patch
from lib import agent


def test_seed_neutral_prompt_when_no_opinion():
    captured = {}

    def fake(system, user, **kw):
        captured["system"] = system
        return {"queries": ["a", "b"]}

    with patch("lib.agent.chat_json", side_effect=fake):
        qs = agent._llm_seed("Elden Ring", opinion=None)
    assert qs == ["a", "b"]
    assert "opinion" not in captured["system"].lower()


def test_seed_biases_pro_con_when_opinion_present():
    captured = {}

    def fake(system, user, **kw):
        captured["system"] = system
        captured["user"] = user
        return {"queries": ["a"]}

    with patch("lib.agent.chat_json", side_effect=fake):
        agent._llm_seed("Elden Ring", opinion="I want to play it")
    blob = (captured["system"] + captured["user"]).lower()
    assert "support" in blob and ("challeng" in blob or "against" in blob)


def test_seed_falls_back_to_topic_on_llm_error():
    with patch("lib.agent.chat_json", side_effect=RuntimeError("x")):
        assert agent._llm_seed("Topic", opinion=None) == ["Topic"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_opinion.py -v`
Expected: FAIL — `_llm_seed() got an unexpected keyword argument 'opinion'`

- [ ] **Step 3: Write minimal implementation**

In `lib/agent.py`, replace `SEED_SYS`/`NEXT_SYS` usage. Update the two helpers and `run_agent` signature.

Replace the `_llm_seed` function (currently near line 47) with:

```python
_SEED_NEUTRAL = (
    "Generate 5 diverse, complementary search queries for social-media research "
    'on the user\'s topic. Output JSON: {"queries": ["..."]}'
)
_SEED_OPINION = (
    "Generate 6 diverse search queries for social-media research on the topic. "
    "The user holds an opinion. Half the queries must seek evidence SUPPORTING "
    "the opinion, half must seek evidence CHALLENGING / against it. "
    'Output JSON: {"queries": ["..."]}'
)


def _llm_seed(topic: str, opinion: str | None = None) -> list[str]:
    system = _SEED_OPINION if opinion else _SEED_NEUTRAL
    user = f"Topic: {topic}"
    if opinion:
        user += f'\nUser opinion: "{opinion}"'
    try:
        out = chat_json(system, user, stage="seed")
    except Exception:
        return [topic]
    qs = [str(q) for q in out.get("queries", []) if q]
    return qs[:6] or [topic]
```

Replace `_llm_next` (near line 65) with an opinion-aware version:

```python
def _llm_next(topic: str, labels: list[str], opinion: str | None = None) -> dict:
    extra = (
        f' The user opinion is "{opinion}"; prioritize under-covered angles that '
        "could support OR challenge it."
        if opinion else ""
    )
    system = (
        "Given cluster labels found so far and the topic, decide: stop or expand. "
        "If expand, propose up to 3 new search queries targeting under-covered "
        "angles." + extra +
        ' Output JSON: {"action": "stop"|"expand", "queries": ["..."]}'
    )
    try:
        return chat_json(system, f"Topic: {topic}\nLabels so far:\n- " + "\n- ".join(labels), stage="next")
    except Exception:
        return {"action": "stop", "queries": []}
```

Delete the old module-level `SEED_SYS` and `NEXT_SYS` constants.

Update `run_agent` signature (near line 113) and the two call sites:

```python
def run_agent(topic: str, sources: list[str], run_id: str | None = None,
              opinion: str | None = None) -> str:
```

Change the seed call (near line 124):
```python
    seeds = _llm_seed(topic, opinion)
```
Change the expand call (near line 256):
```python
        decision = _llm_next(topic, [c["label"] for c in cluster_meta], opinion)
```

Add the evidence build after the briefing block (right before the final
`BUS.publish(run_id, {"type": "done", ...})`):

```python
    try:
        from .evidence import build as build_evidence
        build_evidence(run_id, opinion)
        BUS.publish(run_id, {"type": "evidence_ready",
                             "url": f"/run/{run_id}/evidence"})
    except Exception as e:
        BUS.publish(run_id, {"type": "evidence_error", "err": str(e)})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_agent_opinion.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — all previously-passing tests still green.

- [ ] **Step 6: Commit**

```bash
git add lib/agent.py tests/test_agent_opinion.py
git commit -m "feat(agent): opinion-biased queries + evidence.build hook"
```

---

## Task 4: Server wiring — `server.py`

**Files:**
- Modify: `server.py` (`/run` handler near line 205; add new route)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server_evidence.py
from __future__ import annotations
import json
from unittest.mock import patch
import server as srv
from lib.store import write_json


def _client():
    srv.app.config["TESTING"] = True
    return srv.app.test_client()


def test_run_passes_opinion_to_agent(monkeypatch):
    seen = {}

    def fake_run(topic, sources, run_id=None, opinion=None):
        seen["opinion"] = opinion
        return run_id or "rid"

    monkeypatch.setattr(srv, "run_agent", fake_run)
    # run agent is launched in a thread; call synchronously for the test
    monkeypatch.setattr(srv.threading, "Thread",
                        lambda target, daemon=None: type("T", (), {"start": target})())
    c = _client()
    r = c.post("/run", json={"topic": "Elden Ring", "sources": ["reddit"],
                             "opinion": "I want to play it"})
    assert r.status_code == 200
    assert seen["opinion"] == "I want to play it"


def test_evidence_endpoint_serves_json(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.store.ROOT", tmp_path / "runs")
    write_json("rid", "evidence.json", {"opinion": None, "claims": []})
    c = _client()
    r = c.get("/run/rid/evidence")
    assert r.status_code == 200
    assert r.get_json()["claims"] == []


def test_evidence_endpoint_404_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.store.ROOT", tmp_path / "runs")
    c = _client()
    r = c.get("/run/none/evidence")
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server_evidence.py -v`
Expected: FAIL — `/run/<id>/evidence` returns 404 via Flask default (no route) / opinion not threaded.

- [ ] **Step 3: Write minimal implementation**

In `server.py`, inside `start_run()` (near line 206) read the opinion and pass it.
Find where `topic`/`sources` are parsed and the `go()` closure calls `run_agent`. Add:

```python
    opinion = (data.get("opinion") or "").strip() or None
```
and pass it through the thread target:
```python
    def go():
        ...
        run_agent(topic, sources, run_id=run_id, opinion=opinion)
```
(Keep the existing BYOK apply/restore wrapping unchanged; only add the
`opinion=opinion` keyword to the `run_agent` call.)

Add a new route after the briefing routes (near line 363):

```python
@app.route("/run/<run_id>/evidence")
def run_evidence(run_id):
    from lib.store import read_json
    data = read_json(run_id, "evidence.json")
    if data is None:
        return jsonify({"error": "not generated"}), 404
    return jsonify(data)
```

Confirm `import threading` exists near the top of `server.py`; if the run is
launched via `threading.Thread`, the test monkeypatches `srv.threading`. If the
file uses a bare `Thread` import instead, adjust the test import accordingly
before running.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_server_evidence.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server_evidence.py
git commit -m "feat(server): opinion on /run + GET /run/<id>/evidence"
```

---

## Task 5: Dashboard UI — `templates/index.html`

No automated test (no build step / manual smoke). Keep additive; do not break
existing run flow, SSE log, or briefing pill.

- [ ] **Step 1: Add the opinion input**

Next to the existing topic input, add:

```html
<textarea id="opinion" rows="2"
  placeholder="My Opinion (optional) — e.g. I want to play Elden Ring because I heard good things"></textarea>
```

- [ ] **Step 2: Send opinion on run start**

In the JS that POSTs to `/run`, include the field:

```js
body: JSON.stringify({
  topic, sources,
  opinion: document.getElementById('opinion').value.trim() || null,
})
```

- [ ] **Step 3: Add the tabbed results container**

After the existing results area, add a tab bar + panels (IDs the JS will fill):

```html
<div id="evidence" hidden>
  <nav class="ev-tabs">
    <button data-tab="summary">Summary</button>
    <button data-tab="overview">Overview</button>
    <button data-tab="consensus">Consensus</button>
    <button data-tab="viz">Evidence</button>
    <button data-tab="screenA" class="op-only">Why Right</button>
    <button data-tab="screenB" class="op-only">Why Wrong</button>
    <button data-tab="uncertainty">Uncertainty</button>
    <button data-tab="assessment">Assessment</button>
  </nav>
  <section data-panel="summary"></section>
  <section data-panel="overview" hidden></section>
  <section data-panel="consensus" hidden></section>
  <section data-panel="viz" hidden>
    <canvas id="chartSentiment"></canvas>
    <canvas id="chartProCon"></canvas>
    <canvas id="chartConfidence"></canvas>
  </section>
  <section data-panel="screenA" hidden></section>
  <section data-panel="screenB" hidden></section>
  <section data-panel="uncertainty" hidden></section>
  <section data-panel="assessment" hidden></section>
</div>
```

- [ ] **Step 4: Fetch + render on `evidence_ready`**

In the SSE handler, on `type === "evidence_ready"`:

```js
const ev = await (await fetch(e.url)).json();
renderEvidence(ev);
```

`renderEvidence(ev)` must:
- Unhide `#evidence`; toggle `.op-only` tabs by `ev.opinion` truthiness.
- Summary panel: `ev.exec_summary` (plain_topic, key_findings, agreements,
  disagreements, conclusion) as labelled lists.
- Overview: `ev.topic_overview`.
- Consensus: four lists from `ev.community_consensus`.
- screenA/screenB: render `ev.screen_a`/`ev.screen_b` as claim cards showing
  `text`, a confidence bar (`confidence`), `evidence_strength` badge,
  `reasoning`, and `source_categories` chips.
- Uncertainty: `ev.uncertainty` list.
- Assessment: `ev.final_assessment`.
- Charts (Chart.js, already CDN-loaded — confirm `<script src=".../chart.js">`
  is present; if not, add it): only instantiate a chart when its data is
  non-empty.
  - `chartSentiment`: aggregate pos/neu/neg across claims' clusters (doughnut).
  - `chartProCon`: count of pro vs con claims (bar).
  - `chartConfidence`: per-claim `confidence` (horizontal bar, labelled by
    truncated `text`).

Tab switching: clicking a `[data-tab]` button unhides the matching
`[data-panel]` and hides siblings.

- [ ] **Step 5: Manual smoke test**

Run: `.venv/bin/python server.py` then open `http://localhost:5000`.
- With opinion filled: after a run, `Why Right` / `Why Wrong` tabs appear and
  populate; charts render.
- With opinion empty: `.op-only` tabs hidden; Summary/Consensus/Assessment
  populate; neutral claims listed.

- [ ] **Step 6: Commit**

```bash
git add templates/index.html
git commit -m "feat(ui): opinion input + evidence tabs + charts"
```

---

## Task 6: Docs + final verification

- [ ] **Step 1: Update CLAUDE.md layout note**

Add to the `lib/` listing in `CLAUDE.md`:
```
  evidence.py     opinion-aware evidence.json builder
  evidence_score.py  pure ranking/confidence math
```

- [ ] **Step 2: Run the full test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — all green, including the 3 new test files.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note evidence layer in project memory"
```

---

## Self-Review (completed during planning)

- **Spec coverage:** exec summary → Task 2 `exec_summary` + Task 5 Summary panel;
  opinion mode → Tasks 3/4/5; dual-screen → Task 2 `screen_a/b` + Task 5;
  argument strength (confidence/strength/reasoning) → Task 1 + Task 2 `_enrich_claim`;
  community perspectives → Task 2 `community_consensus`; visualizations → Task 5;
  evidence ranking (5 axes) → Task 1 `rank`; behavior rules → Task 2 `_BEHAVIOR`.
- **Placeholder scan:** none — all steps carry concrete code/commands.
- **Type consistency:** `rank`/`strength_bucket`/`blend`/`category_for` defined in
  Task 1, consumed identically in Task 2; `evidence.json` fields produced in
  Task 2 match Task 5 render contract and Task 4 endpoint.
