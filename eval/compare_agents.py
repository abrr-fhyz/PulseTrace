#!/usr/bin/env python3
"""Head-to-head: PulseTrace agent vs last30days engine on identical topics.

Both run on the same cheap, keyless sources (reddit + hackernews) and the same
Gemini brain, so the comparison isolates *agent/ranking quality*, not API-key
access. A pooled Gemini judge grades the union of both ranked lists once; each
system is then scored against those shared grades (mirrors last30days' own
judged-pool eval methodology).

Usage:
    .venv/bin/python eval/compare_agents.py            # default 3 topics
    .venv/bin/python eval/compare_agents.py --topics "rag" "codex pricing"

Writes raw results to /tmp/agent_compare.json and prints a summary table.
Needs: gemini_paid_api_key in .env.api_keys; uv for the last30days side.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
L30D = ROOT / "last30days-skill"
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from lib import keys  # noqa: E402

keys.load()

from lib.agent import run_agent  # noqa: E402
from lib import store  # noqa: E402
from lib.llm import chat_json  # noqa: E402

K = 8
RELEVANT = 2  # grade >= 2 counts as relevant for precision
SOURCES_PT = ["reddit", "hn"]
SEARCH_L30D = "reddit,hackernews"
DEFAULT_TOPICS = [
    "retrieval augmented generation",
    "thoughts on OpenAI Codex pricing",
    "best budget noise cancelling headphones 2026",
]


# ---------- run each system, normalize to ranked [{url,text,source}] ----------

def run_pulsetrace(topic: str) -> tuple[list[dict], float]:
    t0 = time.time()
    run_id = store.new_run_id()
    try:
        run_agent(topic, SOURCES_PT, run_id=run_id)
    except Exception as e:  # a crash is a real quality signal; record empty
        print(f"  [pt] run_agent error: {e}", flush=True)
        return [], time.time() - t0
    elapsed = time.time() - t0
    try:
        posts = store.read_json(run_id, "posts.json") or []
        clusters = store.read_json(run_id, "clusters.json") or []
    except Exception:
        return [], elapsed
    by_id = {p["id"]: p for p in posts}
    # Round-robin across clusters' influence-ranked top_posts for diversity.
    ranked: list[dict] = []
    seen: set[str] = set()
    pools = [c.get("top_posts", []) for c in clusters]
    for depth in range(max((len(p) for p in pools), default=0)):
        for pool in pools:
            if depth < len(pool):
                pid = pool[depth]
                if pid in by_id and pid not in seen:
                    seen.add(pid)
                    p = by_id[pid]
                    ranked.append({"url": p.get("url") or "", "text": p.get("text") or "",
                                   "source": p.get("source") or ""})
    return ranked[:K], elapsed


def run_last30days(topic: str) -> tuple[list[dict], float]:
    engine = "skills/last30days/scripts/last30days.py"
    cmd = ["uv", "run", "python", engine, topic, "--emit=json",
           "--quick", "--search", SEARCH_L30D]
    t0 = time.time()
    try:
        res = subprocess.run(cmd, cwd=str(L30D), capture_output=True,
                             text=True, timeout=300)
    except subprocess.SubprocessError as e:
        print(f"  [l30d] subprocess error: {e}", flush=True)
        return [], time.time() - t0
    elapsed = time.time() - t0
    try:
        report = json.loads(res.stdout)
    except json.JSONDecodeError:
        print("  [l30d] non-JSON stdout", flush=True)
        return [], elapsed
    ranked: list[dict] = []
    for row in report.get("ranked_candidates", [])[:K]:
        srcs = row.get("sources") or []
        if not srcs and isinstance(row.get("source"), str):
            srcs = [row["source"]]
        ranked.append({
            "url": str(row.get("url") or ""),
            "text": str(row.get("title") or row.get("text") or ""),
            "source": ", ".join(srcs) if srcs else "",
        })
    return ranked, elapsed


# ---------- pooled Gemini judge ----------

def judge_pool(topic: str, items: list[dict]) -> dict[str, int]:
    """Grade each unique item 0-3 for relevance to topic. Keyed by url|text."""
    if not items:
        return {}
    listing = "\n".join(
        f"[{i}] ({it['source']}) {it['text'][:200]}" for i, it in enumerate(items)
    )
    system = (
        "You are a strict search-relevance judge. Grade how well each result "
        "answers or informs the user's research topic. Scale: 0=irrelevant, "
        "1=tangential, 2=relevant, 3=highly relevant/on-topic. "
        'Output JSON: {"grades": {"0": 2, "1": 0, ...}} for every index.'
    )
    user = f"Topic: {topic}\n\nResults:\n{listing}"
    try:
        out = chat_json(system, user, max_tokens=600, stage="judge")
        raw = out.get("grades", {})
    except Exception as e:
        print(f"  [judge] error: {e}", flush=True)
        return {}
    grades: dict[str, int] = {}
    for i, it in enumerate(items):
        g = raw.get(str(i), raw.get(i, 0))
        try:
            grades[_key(it)] = max(0, min(3, int(g)))
        except (ValueError, TypeError):
            grades[_key(it)] = 0
    return grades


def _key(it: dict) -> str:
    return it.get("url") or it.get("text", "")[:80]


# ---------- metrics ----------

def precision_at_k(ranked: list[dict], grades: dict[str, int], k: int = 5) -> float:
    top = ranked[:k]
    if not top:
        return 0.0
    hits = sum(1 for it in top if grades.get(_key(it), 0) >= RELEVANT)
    return hits / len(top)


def ndcg_at_k(ranked: list[dict], grades: dict[str, int], pool_grades: list[int],
              k: int = 5) -> float:
    top = ranked[:k]
    if not top:
        return 0.0
    dcg = sum((2 ** grades.get(_key(it), 0) - 1) / math.log2(i + 2)
              for i, it in enumerate(top))
    ideal = sorted(pool_grades, reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def mean_grade(ranked: list[dict], grades: dict[str, int]) -> float:
    if not ranked:
        return 0.0
    return sum(grades.get(_key(it), 0) for it in ranked) / len(ranked)


def n_sources(ranked: list[dict]) -> int:
    s: set[str] = set()
    for it in ranked:
        for part in it["source"].split(","):
            if part.strip():
                s.add(part.strip())
    return len(s)


def jaccard_urls(a: list[dict], b: list[dict]) -> float:
    ua = {it["url"] for it in a if it["url"]}
    ub = {it["url"] for it in b if it["url"]}
    if not (ua or ub):
        return 0.0
    return len(ua & ub) / len(ua | ub)


# ---------- driver ----------

def evaluate(topics: list[str]) -> dict:
    per_topic = []
    for topic in topics:
        print(f"\n=== TOPIC: {topic} ===", flush=True)
        print("  running pulsetrace...", flush=True)
        pt_ranked, pt_time = run_pulsetrace(topic)
        print(f"  pulsetrace: {len(pt_ranked)} items, {pt_time:.1f}s", flush=True)
        print("  running last30days...", flush=True)
        l3_ranked, l3_time = run_last30days(topic)
        print(f"  last30days: {len(l3_ranked)} items, {l3_time:.1f}s", flush=True)

        # pooled judge over union (dedupe by key)
        pool: list[dict] = []
        seen: set[str] = set()
        for it in pt_ranked + l3_ranked:
            kk = _key(it)
            if kk and kk not in seen:
                seen.add(kk)
                pool.append(it)
        print(f"  judging pool of {len(pool)}...", flush=True)
        grades = judge_pool(topic, pool)
        pool_grades = list(grades.values())

        row = {
            "topic": topic,
            "pulsetrace": _metrics(pt_ranked, grades, pool_grades, pt_time),
            "last30days": _metrics(l3_ranked, grades, pool_grades, l3_time),
            "url_jaccard": round(jaccard_urls(pt_ranked, l3_ranked), 3),
        }
        per_topic.append(row)
        _print_topic(row)
    return {"per_topic": per_topic, "aggregate": _aggregate(per_topic)}


def _metrics(ranked, grades, pool_grades, elapsed) -> dict:
    return {
        "n_results": len(ranked),
        "n_sources": n_sources(ranked),
        "latency_s": round(elapsed, 1),
        "mean_grade": round(mean_grade(ranked, grades), 3),
        "precision_at_5": round(precision_at_k(ranked, grades), 3),
        "ndcg_at_5": round(ndcg_at_k(ranked, grades, pool_grades), 3),
    }


def _aggregate(rows: list[dict]) -> dict:
    out = {}
    for sys_name in ("pulsetrace", "last30days"):
        keys_ = ("n_results", "n_sources", "latency_s", "mean_grade",
                 "precision_at_5", "ndcg_at_5")
        agg = {k: round(sum(r[sys_name][k] for r in rows) / len(rows), 3)
               for k in keys_} if rows else {}
        out[sys_name] = agg
    return out


def _print_topic(row: dict) -> None:
    print(f"  {'metric':<14}{'pulsetrace':>12}{'last30days':>12}")
    for k in ("n_results", "n_sources", "latency_s", "mean_grade",
              "precision_at_5", "ndcg_at_5"):
        print(f"  {k:<14}{row['pulsetrace'][k]:>12}{row['last30days'][k]:>12}")
    print(f"  url_jaccard: {row['url_jaccard']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topics", nargs="*", default=DEFAULT_TOPICS)
    ap.add_argument("--out", default="/tmp/agent_compare.json")
    args = ap.parse_args()

    results = evaluate(args.topics)
    Path(args.out).write_text(json.dumps(results, indent=2))
    print("\n=== AGGREGATE (mean over topics) ===")
    agg = results["aggregate"]
    print(f"{'metric':<16}{'pulsetrace':>12}{'last30days':>12}")
    for k in ("n_results", "n_sources", "latency_s", "mean_grade",
              "precision_at_5", "ndcg_at_5"):
        print(f"{k:<16}{agg['pulsetrace'][k]:>12}{agg['last30days'][k]:>12}")
    print(f"\nRaw results -> {args.out}")


if __name__ == "__main__":
    main()
