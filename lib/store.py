"""Per-run JSON persistence under data/runs/<run_id>/.

The JSON files remain the source of truth. When a tiered DB is provisioned
(`DATABASE_URL` / `MONGODB_URI` set) writes are *additionally* mirrored to
Postgres/pgvector + Mongo on a best-effort basis — a DB outage degrades to the
file path and never raises into the pipeline.
"""
from __future__ import annotations
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any


ROOT = Path("data/runs")
log = logging.getLogger("pulsetrace.store")


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or "topic"


def new_run_id() -> str:
    return f"{int(time.time())}-{uuid.uuid4().hex[:6]}"


def run_dir(run_id: str) -> Path:
    p = ROOT / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_json(run_id: str, name: str, data: Any) -> None:
    (run_dir(run_id) / name).write_text(json.dumps(data, default=str, indent=2))
    _mirror_to_db(run_id, name, data)


def _mirror_to_db(run_id: str, name: str, data: Any) -> None:
    """Best-effort fan-out of run/post writes to the tiered DB. Silent no-op
    when no DB is configured; never propagates a DB error to the caller."""
    ARTIFACTS = ("evidence.json", "ranked.json", "orchestration_summary.json")
    if name not in ("run.json", "posts.json", "clusters.json") and name not in ARTIFACTS:
        return
    try:
        # Deferred import: heavy optional drivers, only loaded when DB in play.
        from db import get_supabase, get_mongo
        from db.models import PostRecord, RunRecord
    except ImportError:
        return

    pg, mongo = get_supabase(), get_mongo()
    if not (pg.enabled or mongo.enabled):
        return

    try:
        run = read_json(run_id, "run.json") or {}
        topic = run.get("topic", "")
        topic_id = run.get("topic_id") or _slug(topic) or run_id

        if name == "run.json":
            rec = RunRecord(
                run_id=run_id, topic=topic, topic_id=topic_id,
                sources=run.get("sources", []) or [],
                status="completed" if run.get("finished_at") else "running",
                started_at=run.get("started_at"), finished_at=run.get("finished_at"),
                n_posts=int(run.get("n_posts", 0) or 0), meta=run.get("meta", {}) or {},
            )
            if pg.enabled:
                pg.upsert_run(rec)
            return

        if name == "posts.json":
            posts = data if isinstance(data, list) else []
            records = [PostRecord.from_raw(p, run_id=run_id, topic_id=topic_id) for p in posts]
            if pg.enabled:
                pg.insert_posts(records)
            if mongo.enabled:
                mongo.write_session(run_id, topic_id, records, meta={"topic": topic})
            return

        if name == "clusters.json":
            if pg.enabled:
                pg.insert_clusters(run_id, topic_id, data if isinstance(data, list) else [])
            return

        # evidence.json / ranked.json / orchestration_summary.json → jsonb artifact
        if pg.enabled:
            pg.upsert_artifact(run_id, name.removesuffix(".json"), data, topic_id=topic_id)
    except Exception as exc:  # noqa: BLE001 - mirror must never break the run
        log.warning("DB mirror skipped for %s/%s: %s", run_id, name, exc)


def read_json(run_id: str, name: str) -> Any:
    p = run_dir(run_id) / name
    if not p.exists():
        return None
    return json.loads(p.read_text())
