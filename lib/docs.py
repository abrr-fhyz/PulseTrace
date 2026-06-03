"""Live /docs module: access control, content load, live stats."""
from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "data" / "docs_config.json"
RUNS_DIR = ROOT / "data" / "runs"
CONNECTORS_DIR = ROOT / "lib" / "connectors"

DEFAULT_CONFIG = {
    "enabled": True,
    "start": "2026-06-10T00:00",
    "end": "2026-06-14T23:59",
    "override_always_on": False,
}

ADMIN_TOKEN_ENV = "DOCS_ADMIN_TOKEN"
DEFAULT_ADMIN_TOKEN = "pulsetrace-admin"


def admin_token() -> str:
    return os.environ.get(ADMIN_TOKEN_ENV, DEFAULT_ADMIN_TOKEN)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        with CONFIG_PATH.open() as f:
            cfg = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w") as f:
        json.dump(cfg, f, indent=2)


def _parse_dt(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def access_status(cfg: dict | None = None, now: datetime | None = None) -> dict:
    cfg = cfg or load_config()
    now = now or datetime.now()
    if not cfg.get("enabled", False):
        return {"allowed": False, "reason": "disabled", "config": cfg}
    if cfg.get("override_always_on"):
        return {"allowed": True, "reason": "override", "config": cfg}
    start = _parse_dt(cfg.get("start", ""))
    end = _parse_dt(cfg.get("end", ""))
    if start and now < start:
        return {"allowed": False, "reason": "not_yet", "config": cfg, "start": start.isoformat()}
    if end and now > end:
        return {"allowed": False, "reason": "expired", "config": cfg, "end": end.isoformat()}
    return {"allowed": True, "reason": "in_window", "config": cfg}


def live_stats() -> dict:
    run_count = 0
    last_run_ts = None
    if RUNS_DIR.exists():
        runs = sorted(RUNS_DIR.iterdir(), key=lambda p: p.name)
        run_count = len(runs)
        if runs:
            last = runs[-1]
            try:
                last_run_ts = datetime.fromtimestamp(last.stat().st_mtime).isoformat(timespec="seconds")
            except OSError:
                last_run_ts = None
    connectors = []
    if CONNECTORS_DIR.exists():
        for p in sorted(CONNECTORS_DIR.glob("*.py")):
            name = p.stem
            if name in {"base", "__init__"}:
                continue
            connectors.append(name)
    return {
        "run_count": run_count,
        "last_run_ts": last_run_ts,
        "connectors": connectors,
        "connector_count": len(connectors),
    }
