#!/usr/bin/env python3
"""End-to-end orchestrator.

Edit the constants below and run:

    .venv/bin/python scripts/run_e2e.py

It runs every staged pipeline test (tests/stages/test_NN_*.py) in order
against TOPIC, localizing failures to the exact phase:

    1. keys load
    2. provider chat
    3. embedding
    4. HN connector
    5. Facebook connector
    6. seed / next LLM
    7. cluster + label + sentiment
    8. full agent -> results/<slug>_result.json

Final payload at results/<slug>_result.json contains everything the
webapp dashboard renders: KPIs, clusters (label + sentiment + sample
posts with newslinks), topic graph (nodes + edges), and the flat
news_items list with URLs.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


# ─── Configuration — edit these ────────────────────────────────────────────
TOPIC = "openai codex"
ONLY_PHASES: list[str] = []        # e.g. ["02", "03"] to run a subset
STOP_ON_FAIL = False               # True = abort after first FAIL
RAG_QUESTIONS = [                  # questions Stage 14 will run + save to results/
    "What are the main themes in this conversation?",
    "What are the biggest complaints?",
    "Who or what is mentioned most often?",
    "Is sentiment more positive or negative overall?",
]
WEBAPP_URL = "http://127.0.0.1:5000"   # Stage 15 talks to this; skipped if down
# ───────────────────────────────────────────────────────────────────────────


REPO_ROOT = Path(__file__).resolve().parents[1]
STAGES_DIR = REPO_ROOT / "tests" / "stages"
RESULTS_DIR = REPO_ROOT / "results"

PHASE_LABELS = {
    "01": "keys load",
    "02": "provider chat",
    "03": "embedding",
    "04": "HN connector",
    "05": "Facebook connector",
    "06": "seed / next LLM",
    "07": "cluster + label + sentiment",
    "08": "full agent -> results JSON",
    "09": "influence ranking",
    "10": "topic graph",
    "11": "search expansion",
    "12": "multi-source ingestion",
    "13": "entropy + convergence",
    "14": "RAG Q&A -> results JSON",
    "15": "live webapp (HTTP)",
    "16": "provider cascade",
}


def discover_stages() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for p in sorted(STAGES_DIR.glob("test_*.py")):
        m = re.match(r"test_(\d+)_", p.name)
        if m:
            out.append((m.group(1), p))
    return out


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "topic"


def parse_pytest_counts(stdout: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    last = ""
    for ln in stdout.splitlines():
        if "passed" in ln or "failed" in ln or "skipped" in ln or "error" in ln:
            last = ln
    for kind in counts:
        m = re.search(rf"(\d+)\s+{kind}", last)
        if m:
            counts[kind] = int(m.group(1))
    return counts


def run_phase(num: str, path: Path, env: dict) -> dict:
    label = PHASE_LABELS.get(num, path.stem)
    print(f"\n── Phase {num}: {label} {'─' * max(0, 50 - len(label))}")
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(path), "-v",
         "--tb=short", "--no-header", "-rN"],
        cwd=REPO_ROOT, env=env,
        capture_output=True, text=True,
    )
    elapsed = time.time() - t0
    counts = parse_pytest_counts(proc.stdout)
    status = "PASS" if proc.returncode == 0 else "FAIL"
    print(proc.stdout.rstrip())
    if proc.stderr.strip():
        print("--- stderr ---")
        print(proc.stderr.rstrip())
    print(f"── Phase {num} {status}  "
          f"({counts['passed']}p / {counts['failed']}f / {counts['skipped']}s)  "
          f"in {elapsed:.1f}s")
    return {
        "phase": num, "label": label, "file": path.name,
        "status": status, "returncode": proc.returncode,
        "elapsed_sec": round(elapsed, 2), "counts": counts,
    }


def main() -> int:
    env = os.environ.copy()
    env["PT_TEST_TOPIC"] = TOPIC
    env["PT_RAG_QUESTIONS"] = "|".join(RAG_QUESTIONS)
    env["PT_WEBAPP_URL"] = WEBAPP_URL
    env.setdefault("PYTHONUNBUFFERED", "1")

    stages = discover_stages()
    if ONLY_PHASES:
        wanted = set(ONLY_PHASES)
        stages = [s for s in stages if s[0] in wanted]
    if not stages:
        print("no stages matched", file=sys.stderr)
        return 2

    RESULTS_DIR.mkdir(exist_ok=True)
    print(f"E2E topic: {TOPIC!r}")
    print(f"Phases:    {', '.join(n for n, _ in stages)}")
    print(f"Results:   {RESULTS_DIR.relative_to(REPO_ROOT)}/")

    results: list[dict] = []
    for num, path in stages:
        r = run_phase(num, path, env)
        results.append(r)
        if r["status"] == "FAIL" and STOP_ON_FAIL:
            break

    print("\n========== SUMMARY ==========")
    width = max(len(r["label"]) for r in results) + 2
    for r in results:
        print(f"  [{r['phase']}] {r['label']:<{width}} {r['status']:<5} "
              f"{r['counts']['passed']}p / {r['counts']['failed']}f / "
              f"{r['counts']['skipped']}s   {r['elapsed_sec']}s")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    print(f"  -> {n_pass} phases passed, {n_fail} failed")

    main_json = RESULTS_DIR / f"{slug(TOPIC)}_result.json"
    if main_json.exists():
        try:
            data = json.loads(main_json.read_text())
            print(f"  -> webapp JSON: {main_json.relative_to(REPO_ROOT)}  "
                  f"({main_json.stat().st_size} bytes)")
            providers = data.get("providers", {})
            kpis = data.get("kpis", {})
            graph = data.get("graph", {})
            print(f"     chat={providers.get('chat', {}).get('name')}  "
                  f"embed={providers.get('embed', {}).get('name')}  "
                  f"posts={kpis.get('posts')}  "
                  f"clusters={kpis.get('clusters')}  "
                  f"edges={len(graph.get('edges', []))}  "
                  f"stop={data.get('stop_reason')}")
            by_source = kpis.get("by_source") or {}
            if by_source:
                print(f"     by_source: " + ", ".join(
                    f"{k}={v}" for k, v in by_source.items()))
            with_url = sum(1 for n in data.get("news_items", []) if n.get("url"))
            print(f"     news_items with url: {with_url} / {len(data.get('news_items', []))}")
            print(f"     entropy: {data.get('kpis', {}).get('entropy')}  "
                  f"search_iters: {len(data.get('search_log', []))}")
            for c in data.get("clusters", [])[:5]:
                sp = c.get("sentiment_pct", {})
                print(f"       [c{c['id']}] {c['label']:<35} "
                      f"{c['n_members']}p  "
                      f"+{sp.get('pos',0)}% ={sp.get('neu',0)}% -{sp.get('neg',0)}%")
        except Exception as e:
            print(f"  -> webapp JSON exists but unreadable: {e}")
    else:
        print(f"  -> webapp JSON MISSING ({main_json.name}). "
              f"Phase 08 likely failed or was skipped.")

    rag_json = RESULTS_DIR / f"{slug(TOPIC)}_rag.json"
    if rag_json.exists():
        try:
            data = json.loads(rag_json.read_text())
            qa = data.get("qa", [])
            print(f"  -> RAG JSON:    {rag_json.relative_to(REPO_ROOT)}  "
                  f"({rag_json.stat().st_size} bytes, {len(qa)} Q&A)")
            for item in qa[:3]:
                ans = (item.get("answer") or "").strip().replace("\n", " ")
                print(f"       Q: {item.get('question')}")
                print(f"       A: {ans[:140]}{'…' if len(ans) > 140 else ''}")
        except Exception as e:
            print(f"  -> RAG JSON unreadable: {e}")

    report = RESULTS_DIR / f"{slug(TOPIC)}_phases.json"
    report.write_text(json.dumps({
        "topic": TOPIC, "phases": results,
    }, indent=2))
    print(f"  -> phase report: {report.relative_to(REPO_ROOT)}")

    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
