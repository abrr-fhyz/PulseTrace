"""Per-thread chat persistence under data/runs/<run_id>/chats/<thread_id>.json.

Threads are scoped to a run (its post corpus is the RAG evidence). Reuses
lib.store.ROOT so the path holds regardless of launch cwd.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from . import store


def _chats_dir(run_id: str) -> Path:
    p = store.ROOT / run_id / "chats"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _thread_path(run_id: str, thread_id: str) -> Path:
    return store.ROOT / run_id / "chats" / f"{thread_id}.json"


def new_thread(run_id: str, title: str = "New chat") -> dict[str, Any]:
    now = int(time.time())
    return {
        "id": uuid.uuid4().hex[:12],
        "run_id": run_id,
        "title": title,
        "created": now,
        "updated": now,
        "summary": "",
        "archived_count": 0,
        "messages": [],
    }


def append_message(thread: dict, role: str, content: str, *,
                   citations_detail: list | None = None,
                   confidence: float | None = None) -> dict:
    msg: dict[str, Any] = {"role": role, "content": content, "ts": int(time.time())}
    if citations_detail is not None:
        msg["citations_detail"] = citations_detail
    if confidence is not None:
        msg["confidence"] = confidence
    thread["messages"].append(msg)
    return msg


def save_thread(thread: dict) -> None:
    thread["updated"] = max(int(thread.get("updated", 0)), int(time.time()))
    path = _thread_path(thread["run_id"], thread["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(thread, default=str, indent=2))


def load_thread(run_id: str, thread_id: str) -> dict | None:
    path = _thread_path(run_id, thread_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def list_threads(run_id: str) -> list[dict]:
    chats = store.ROOT / run_id / "chats"
    if not chats.exists():
        return []
    rows: list[dict] = []
    for f in chats.glob("*.json"):
        try:
            t = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        rows.append({
            "id": t.get("id", f.stem),
            "title": t.get("title", "Chat"),
            "created": t.get("created", 0),
            "updated": t.get("updated", 0),
            "message_count": len(t.get("messages", [])),
        })
    rows.sort(key=lambda r: r["updated"], reverse=True)
    return rows


def delete_thread(run_id: str, thread_id: str) -> bool:
    path = _thread_path(run_id, thread_id)
    if not path.exists():
        return False
    path.unlink()
    return True
