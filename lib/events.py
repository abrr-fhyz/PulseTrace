"""Thread-safe per-run event queues for SSE streaming."""
from __future__ import annotations
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any


_LOG_DIR = Path(os.environ.get("PT_EVENT_LOG_DIR", "data/event_logs"))
_MIRROR_STDOUT = os.environ.get("PT_EVENT_QUIET", "0") != "1"


class EventBus:
    def __init__(self) -> None:
        self._queues: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()
        self._log_handles: dict[str, Any] = {}

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        self._mirror(run_id, event)
        with self._lock:
            qs = list(self._queues.get(run_id, []))
        for q in qs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass

    def _mirror(self, run_id: str, event: dict[str, Any]) -> None:
        line = f"[ev {run_id} {event.get('type', '?')}] {json.dumps(event, default=str)}"
        if _MIRROR_STDOUT:
            print(line, file=sys.stdout, flush=True)
        try:
            with self._lock:
                fh = self._log_handles.get(run_id)
                if fh is None:
                    _LOG_DIR.mkdir(parents=True, exist_ok=True)
                    fh = open(_LOG_DIR / f"{run_id}.log", "a", buffering=1)
                    self._log_handles[run_id] = fh
            ts = time.strftime("%H:%M:%S")
            fh.write(f"{ts} {line}\n")
        except Exception:
            pass

    def subscribe(self, run_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1024)
        with self._lock:
            self._queues.setdefault(run_id, []).append(q)
        return q

    def close(self, run_id: str) -> None:
        with self._lock:
            qs = self._queues.pop(run_id, [])
            fh = self._log_handles.pop(run_id, None)
        for q in qs:
            try:
                q.put_nowait({"type": "_close"})
            except queue.Full:
                pass
        if fh:
            try: fh.close()
            except Exception: pass


BUS = EventBus()


def sse_format(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"
