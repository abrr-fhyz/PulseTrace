#!/usr/bin/env python3
"""PulseTrace search-quality eval, scored against a frozen last30days baseline.

PulseTrace runs live (run_agent -> clusters' top_posts) and is graded by a
Gemini relevance judge (Precision@5, nDCG@5, mean grade). The last30days column
is a frozen baseline (eval/l30d_baseline.json) captured once on the matched
model — the upstream engine is NOT a dependency of this repo. To re-capture the
baseline, clone github.com/mvanhorn/last30days-skill and run the pre-refactor
harness; see .claude/memory/last30days-benchmark.md.

Usage:
    .venv/bin/python eval/compare_agents.py            # default 3 topics
    GEMINI_CHAT_MODEL=gemini-3.1-flash-lite .venv/bin/python eval/compare_agents.py

Writes raw results to /tmp/agent_compare.json and prints a summary table.
Needs gemini_paid_api_key in .env.api_keys.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from lib import keys  # noqa: E402

keys.load()

from lib.agent import run_agent  # noqa: E402
from lib import store  # noqa: E402
from lib.llm import chat_json  # noqa: E402

K = 8
RELEVANT = 2
SOURCES_PT = ["reddit", "hn"]
BASELINE_FILE = ROOT / "eval" / "l30d_baseline.json"
DEFAULT_TOPICS = [
    "retrieval augmented generation",
    "thoughts on OpenAI Codex pricing",
    "best budget noise cancelling headphones 2026",
]


def _load_baseline() -> dict:
    try:
        return json.loads(BASELINE_FILE.read_text())
    except (OSError, ValueError):
        return {"per_topic": {}, "aggregate": {}}


def run_pulsetrace(topic: str) -> tuple[list[dict], float]:
    t0 = time.time()
    run_id = store.new_run_id()
    try:
        run_agent(topic, SOURCES_PT, run_id=run_id)
    except Exception as e:
        print(f"  [pt] run_agent error: {e}", flush=True)
        return [], time.time() - t0
    elapsed = time.time() - t0
    try:
        posts = store.read_json(run_id, "posts.json") or []
        clusters = store.read_json(run_id, "clusters.json") or []
    except Exception:
        return [], elapsed
    by_id = {p["id"]: p for p in posts}
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


def judge_pool(topic: str, items: list[dict]) -> dict[str, int]:
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
    try:
        out = chat_json(system, f"Topic: {topic}\n\nResults:\n{listing}", max_tokens=600, stage="judge")
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


def precision_at_k(ranked, grades, k=5) -> float:
    top = ranked[:k]
    if not top:
        return 0.0
    return sum(1 for it in top if grades.get(_key(it), 0) >= RELEVANT) / len(top)


def ndcg_at_k(ranked, grades, pool_grades, k=5) -> float:
    top = ranked[:k]
    if not top:
        return 0.0
    dcg = sum((2 ** grades.get(_key(it), 0) - 1) / math.log2(i + 2)
              for i, it in enumerate(top))
    ideal = sorted(pool_grades, reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def mean_grade(ranked, grades) -> float:
    if not ranked:
        return 0.0
    return sum(grades.get(_key(it), 0) for it in ranked) / len(ranked)


def n_sources(ranked) -> int:
    s: set[str] = set()
    for it in ranked:
        for part in it["source"].split(","):
            if part.strip():
                s.add(part.strip())
    return len(s)


METRIC_KEYS = ("n_results", "n_sources", "latency_s", "mean_grade",
               "precision_at_5", "ndcg_at_5")


def _metrics(ranked, grades, pool_grades, elapsed) -> dict:
    return {
        "n_results": len(ranked),
        "n_sources": n_sources(ranked),
        "latency_s": round(elapsed, 1),
        "mean_grade": round(mean_grade(ranked, grades), 3),
        "precision_at_5": round(precision_at_k(ranked, grades), 3),
        "ndcg_at_5": round(ndcg_at_k(ranked, grades, pool_grades), 3),
    }


def evaluate(topics: list[str], baseline: dict) -> dict:
    per_topic = []
    for topic in topics:
        print(f"\n=== TOPIC: {topic} ===", flush=True)
        pt_ranked, pt_time = run_pulsetrace(topic)
        print(f"  pulsetrace: {len(pt_ranked)} items, {pt_time:.1f}s", flush=True)
        grades = judge_pool(topic, pt_ranked)
        pool_grades = list(grades.values())
        row = {
            "topic": topic,
            "pulsetrace": _metrics(pt_ranked, grades, pool_grades, pt_time),
            "last30days_baseline": baseline.get("per_topic", {}).get(topic),
        }
        per_topic.append(row)
        _print_topic(row)
    agg_pt = {k: round(sum(r["pulsetrace"][k] for r in per_topic) / len(per_topic), 3)
              for k in METRIC_KEYS} if per_topic else {}
    return {
        "per_topic": per_topic,
        "aggregate": {"pulsetrace": agg_pt,
                      "last30days_baseline": baseline.get("aggregate", {})},
    }


def _print_topic(row: dict) -> None:
    base = row.get("last30days_baseline") or {}
    print(f"  {'metric':<14}{'pulsetrace':>12}{'l30d(base)':>12}")
    for k in METRIC_KEYS:
        print(f"  {k:<14}{row['pulsetrace'][k]:>12}{base.get(k, '-'):>12}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topics", nargs="*", default=DEFAULT_TOPICS)
    ap.add_argument("--out", default="/tmp/agent_compare.json")
    args = ap.parse_args()

    baseline = _load_baseline()
    results = evaluate(args.topics, baseline)
    Path(args.out).write_text(json.dumps(results, indent=2))
    agg = results["aggregate"]
    base = agg.get("last30days_baseline", {})
    print("\n=== AGGREGATE (PulseTrace live vs frozen l30d baseline) ===")
    print(f"{'metric':<16}{'pulsetrace':>12}{'l30d(base)':>12}")
    for k in METRIC_KEYS:
        print(f"{k:<16}{agg['pulsetrace'].get(k, '-'):>12}{base.get(k, '-'):>12}")
    print(f"\nl30d column = frozen baseline ({BASELINE_FILE.name}); not re-run.")
    print(f"Raw results -> {args.out}")


if __name__ == "__main__":
    main()
