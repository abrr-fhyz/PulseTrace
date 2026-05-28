"""Per-run JSON persistence under data/runs/<run_id>/."""
from __future__ import annotations
import json
import time
import uuid
from pathlib import Path
from typing import Any


ROOT = Path("data/runs")


def new_run_id() -> str:
    return f"{int(time.time())}-{uuid.uuid4().hex[:6]}"


def run_dir(run_id: str) -> Path:
    p = ROOT / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_json(run_id: str, name: str, data: Any) -> None:
    (run_dir(run_id) / name).write_text(json.dumps(data, default=str, indent=2))


def read_json(run_id: str, name: str) -> Any:
    p = run_dir(run_id) / name
    if not p.exists():
        return None
    return json.loads(p.read_text())
