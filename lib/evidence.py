"""Opinion-aware evidence layer: build evidence.json from a completed run."""
from __future__ import annotations
import copy
import logging
import re
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
_VOICE = (
    "Write for an ordinary reader, not an engineer. NEVER expose internal "
    "machinery: do not write 'cluster', 'Cluster 0', 'Unlabeled', 'n=34', "
    "'sentiment score', or numeric scores like '(0.735)'. The clusters below are "
    "just groups of similar posts — refer to them in plain words like 'many "
    "people', 'a recurring theme', 'one group of posts'. Say what people actually "
    "feel or discuss and why it matters, in warm, conversational, everyday "
    "language."
)

_JARGON = [
    (re.compile(r"\bClusters?\s*\d+(?:\s*(?:,|and|&)\s*\d+)*\s*,?\s*", re.I), ""),
    (re.compile(r"['\"]?\bUnlabeled\b\s*,?\s*['\"]?\s*", re.I), "this group "),
    (re.compile(r"\bn\s*=\s*\d+\b", re.I), ""),
    (re.compile(r"\bsentiment scores?\b", re.I), "overall mood"),
    (re.compile(r"\(\s*[-+]?[01]?\.\d+\s*\)"), ""),
    (re.compile(r"\bhas a (high|low|strong) (negative|positive) sentiment\b", re.I),
     r"reads as strongly \2"),
]
_FIXUP = [
    (re.compile(r"\s{2,}"), " "),
    (re.compile(r"\s+([,.;:!?])"), r"\1"),
    (re.compile(r"\(\s*\)"), ""),
]


def _scrub(v):
    """Strip leaked ML jargon from any user-facing text the LLM produced."""
    if isinstance(v, str):
        for pat, repl in _JARGON:
            v = pat.sub(repl, v)
        for pat, repl in _FIXUP:
            v = pat.sub(repl, v)
        v = v.strip()
        return v[0].upper() + v[1:] if v else v
    if isinstance(v, list):
        return [_scrub(x) for x in v]
    if isinstance(v, dict):
        return {k: _scrub(x) for k, x in v.items()}
    return v
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
        "exec_summary": _scrub(llm.get("exec_summary", _NEUTRAL["exec_summary"])),
        "topic_overview": _scrub(llm.get("topic_overview", "")),
        "community_consensus": _scrub(llm.get("community_consensus", _NEUTRAL["community_consensus"])),
        "claims": claims,
        "screen_a": [c for c in claims if c["side"] == "pro"] if opinion else [],
        "screen_b": [c for c in claims if c["side"] == "con"] if opinion else [],
        "uncertainty": _scrub(llm.get("uncertainty", [])),
        "final_assessment": _scrub(llm.get("final_assessment", "")),
    }
    write_json(run_id, "evidence.json", out)
    return out


def _enrich_claim(claim: dict, members_by_cid: dict[int, list[Post]],
                  max_members: int, now: int) -> dict:
    cids = _coerce_cids(claim.get("cluster_ids", []))
    posts: list[Post] = []
    for cid in cids:
        posts.extend(members_by_cid.get(cid, []))
    ranking = es.rank(posts, max_members, now)
    computed = sum(ranking.values()) / len(ranking)
    llm_conf = _clamp(claim.get("llm_confidence", 0.0))
    cats = sorted({es.category_for(p.source) for p in posts}) or ["unknown"]
    return {
        "text": _scrub(str(claim.get("text", ""))),
        "side": claim.get("side", "neutral"),
        "confidence": es.blend(computed, llm_conf),
        "evidence_strength": es.strength_bucket(ranking),
        "reasoning": _scrub(str(claim.get("reasoning", ""))),
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
        "report from social-media discussion. " + _BEHAVIOR + " " + _VOICE + " " + _SCHEMA
    )
    user = f"Topic: {topic}\n{stance}\n\nCluster findings:\n{labels}"
    try:
        out = chat_json(system, user, max_tokens=1500, stage="evidence")
        if not isinstance(out, dict):
            raise ValueError("non-dict")
        return out
    except Exception as e:
        _LOG.warning("evidence LLM failed: %s", e)
        return copy.deepcopy(_NEUTRAL)


def _to_post(d: dict) -> Post:
    return Post(
        id=d.get("id", ""), source=d.get("source", ""), text=d.get("text", ""),
        author=d.get("author"), url=d.get("url"), ts=int(d.get("ts", 0) or 0),
        reactions=int(d.get("reactions", 0) or 0),
        comments=int(d.get("comments", 0) or 0),
        shares=int(d.get("shares", 0) or 0), raw=d.get("raw", {}) or {},
    )


def _coerce_cids(raw) -> list[int]:
    out: list[int] = []
    for x in raw if isinstance(raw, list) else []:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def _clamp(v) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0
