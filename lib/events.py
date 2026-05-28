"""Thread-safe per-run event queues for SSE streaming."""
from __future__ import annotations
import json
import queue
import threading
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._queues: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            qs = list(self._queues.get(run_id, []))
        for q in qs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass

    def subscribe(self, run_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1024)
        with self._lock:
            self._queues.setdefault(run_id, []).append(q)
        return q

    def close(self, run_id: str) -> None:
        with self._lock:
            qs = self._queues.pop(run_id, [])
        for q in qs:
            try:
                q.put_nowait({"type": "_close"})
            except queue.Full:
                pass


BUS = EventBus()


def sse_format(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"
