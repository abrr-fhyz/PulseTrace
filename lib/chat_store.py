"""Per-thread chat persistence: file (memory working-set + fallback) plus a
Supabase dual-write that is the durable source of truth when enabled.

File path: data/runs/<run_id>/chats/<thread_id>.json (via lib.store.ROOT).
DB: `conversations` (title/summary/archived_count) + append-only `messages`.
Memory compaction (lib.chat_memory) only trims the file working-set; the DB
keeps full history. The answering path reconstructs the compacted working-set
from the DB so memory logic stays unchanged.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from . import store


def _pg():
    """Process-wide Supabase singleton, or None when the DB layer is absent
    or misconfigured (chat must never crash on a DB setup problem)."""
    try:
        from db import get_supabase
        return get_supabase()
    except Exception:
        return None


def _topic_id(run_id: str) -> str:
    run = store.read_json(run_id, "run.json") or {}
    return run.get("topic_id") or store._slug(run.get("topic", "")) or run_id


def _conv_row(thread: dict) -> dict:
    return {
        "id": thread["id"],
        "topic_id": thread.get("topic_id") or _topic_id(thread["run_id"]),
        "run_id": thread["run_id"],
        "title": thread.get("title", "New chat"),
        "summary": thread.get("summary", ""),
        "archived_count": int(thread.get("archived_count", 0)),
    }


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
        "topic_id": _topic_id(run_id),
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

    pg = _pg()
    if pg and pg.enabled:
        meta: dict[str, Any] = {}
        if citations_detail is not None:
            meta["citations_detail"] = citations_detail
        if confidence is not None:
            meta["confidence"] = confidence
        if pg.upsert_conversation(_conv_row(thread)):  # ensure FK row exists first
            pg.insert_message(thread["id"], role, content, meta)
    return msg


def save_thread(thread: dict) -> None:
    thread["updated"] = max(int(thread.get("updated", 0)), int(time.time()))
    path = _thread_path(thread["run_id"], thread["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(thread, default=str, indent=2))

    pg = _pg()
    if pg and pg.enabled:
        pg.upsert_conversation(_conv_row(thread))


def _msgs_from_db(rows: list[dict], *, with_meta: bool) -> list[dict]:
    out = []
    for m in rows:
        d: dict[str, Any] = {"role": m["role"], "content": m["content"]}
        if m.get("ts") is not None:
            d["ts"] = m["ts"]
        meta = m.get("metadata") or {}
        if with_meta:
            if "citations_detail" in meta:
                d["citations_detail"] = meta["citations_detail"]
            if "confidence" in meta:
                d["confidence"] = meta["confidence"]
        out.append(d)
    return out


def load_thread(run_id: str, thread_id: str) -> dict | None:
    """Compacted working-set for the answering/memory path (DB-first)."""
    pg = _pg()
    if pg and pg.enabled:
        conv = pg.get_conversation(thread_id)
        if conv:
            archived = int(conv.get("archived_count", 0))
            rows = pg.get_messages(thread_id)[archived * 2:]
            return {
                "id": conv["id"], "run_id": conv["run_id"],
                "topic_id": conv["topic_id"], "title": conv["title"],
                "summary": conv.get("summary", ""), "archived_count": archived,
                "messages": _msgs_from_db(rows, with_meta=False),
            }
    path = _thread_path(run_id, thread_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_thread_full(run_id: str, thread_id: str) -> dict | None:
    """Full history for display (DB-first); file fallback returns the working-set."""
    pg = _pg()
    if pg and pg.enabled:
        conv = pg.get_conversation(thread_id)
        if conv:
            rows = pg.get_messages(thread_id)
            return {
                "id": conv["id"], "run_id": conv["run_id"],
                "topic_id": conv["topic_id"], "title": conv["title"],
                "summary": conv.get("summary", ""),
                "archived_count": int(conv.get("archived_count", 0)),
                "messages": _msgs_from_db(rows, with_meta=True),
            }
    return load_thread(run_id, thread_id)


def list_threads(run_id: str) -> list[dict]:
    pg = _pg()
    if pg and pg.enabled:
        return pg.list_conversations(_topic_id(run_id))
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
    pg = _pg()
    db_deleted = bool(pg and pg.enabled and pg.delete_conversation(thread_id))
    path = _thread_path(run_id, thread_id)
    file_deleted = path.exists()
    if file_deleted:
        path.unlink()
    return db_deleted or file_deleted
