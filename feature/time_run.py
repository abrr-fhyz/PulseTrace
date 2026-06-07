"""Timed agent run. Usage: .venv/bin/python feature/time_run.py "Topic" [sources]

Prints elapsed wall-clock at each pipeline event so per-iter cost is visible.
"""
from __future__ import annotations
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PT_EVENT_QUIET", "1")  # suppress raw BUS stdout; we print our own

from dotenv import load_dotenv
load_dotenv()
from lib.keys import load as _load_api_keys
_load_api_keys()

from lib.events import BUS
from lib.store import new_run_id
from lib.agent import run_agent

topic = sys.argv[1] if len(sys.argv) > 1 else "Banolota Express"
sources = sys.argv[2].split(",") if len(sys.argv) > 2 else ["facebook"]

run_id = new_run_id()
t0 = time.monotonic()


def listen() -> None:
    q = BUS.subscribe(run_id)
    while True:
        ev = q.get()
        if ev.get("type") == "_close":
            break
        el = time.monotonic() - t0
        t = ev.get("type", "?")
        extra = ""
        if t == "iter_start":
            extra = f"iter={ev.get('iter')} nq={len(ev.get('queries', []))}"
        elif t == "posts_fetched":
            extra = f"n_new={ev.get('n_new')} n_total={ev.get('n_total')}"
        elif t == "deduped":
            extra = f"dropped={ev.get('dropped')} kept={ev.get('kept')}"
        elif t == "clustered":
            extra = f"k={ev.get('k')} H={ev.get('entropy'):.3f}"
        elif t == "saturation":
            extra = f"val={ev.get('value'):.3f}"
        elif t == "done":
            extra = f"stop={ev.get('stop_reason')} n_posts={ev.get('n_posts')}"
        if t in {"iter_start", "posts_fetched", "deduped", "clustered",
                 "saturation", "labeled", "briefing_ready", "done"}:
            print(f"[{el:7.1f}s] {t:14s} {extra}", flush=True)


th = threading.Thread(target=listen, daemon=True)
th.start()
time.sleep(0.2)

print(f"topic={topic!r} sources={sources}")
run_agent(topic, sources, run_id=run_id)
th.join(timeout=2)
print(f"\n=== TOTAL {time.monotonic() - t0:.1f}s ===")
