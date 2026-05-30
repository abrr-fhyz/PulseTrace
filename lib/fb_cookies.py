"""Facebook cookie staleness + auto-refresh job manager.

Two responsibilities:

1. `status()` — is `info/cookies.json` present and < 4h old? Surfaces what the
   UI needs to decide between "use existing", "refresh via UI", "run manually".

2. `Job` / `start_refresh()` / `confirm()` — spawns `scripts/fb_login.py` as a
   subprocess, pumps its stdout into a queue so the Flask SSE handler can fan
   it out, and writes "\\n" to its stdin when the user clicks "Done" (the
   script blocks on `input()` until the user has finished logging in inside
   the visible Chromium window).
"""
from __future__ import annotations
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue, Empty


COOKIE_PATH = Path("info/cookies.json")
STALE_MARKER = Path("info/cookies.stale")
STALE_AFTER_SEC = int(os.environ.get("PT_FB_COOKIE_TTL_SEC", str(4 * 3600)))
SCRIPT_PATH = Path("scripts/fb_login.py")


def mark_stale(reason: str = "") -> None:
    """Connector calls this when it detects a login redirect — forces the
    next /fb/cookies/status to report stale=True even if the file is young."""
    try:
        STALE_MARKER.parent.mkdir(parents=True, exist_ok=True)
        STALE_MARKER.write_text(reason or "marked-stale")
    except OSError:
        pass


def _clear_stale_marker() -> None:
    try:
        STALE_MARKER.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def cookie_age_seconds() -> int | None:
    if not COOKIE_PATH.exists():
        return None
    return int(time.time() - COOKIE_PATH.stat().st_mtime)


def status() -> dict:
    age = cookie_age_seconds()
    marker_reason = None
    if STALE_MARKER.exists():
        try:
            marker_reason = STALE_MARKER.read_text().strip() or "marker present"
        except OSError:
            marker_reason = "marker present"
    if age is None:
        return {"exists": False, "stale": True, "age_seconds": None,
                "ttl_seconds": STALE_AFTER_SEC, "reason": "no cookies file"}
    stale = age >= STALE_AFTER_SEC or marker_reason is not None
    reason = marker_reason if marker_reason else (
        "older than ttl" if age >= STALE_AFTER_SEC
        else f"{age}s old (< {STALE_AFTER_SEC}s ttl)")
    return {
        "exists": True,
        "stale": stale,
        "age_seconds": age,
        "ttl_seconds": STALE_AFTER_SEC,
        "reason": reason,
    }


@dataclass
class Job:
    id: str
    proc: subprocess.Popen
    q: Queue
    state: str = "starting"
    exit_code: int | None = None
    started_at: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock)


_JOBS: dict[str, Job] = {}
_jobs_lock = threading.Lock()


def get(job_id: str) -> Job | None:
    with _jobs_lock:
        return _JOBS.get(job_id)


def _pump_stdout(job: Job) -> None:
    proc = job.proc
    assert proc.stdout is not None
    job.q.put({"type": "log", "line": f"[boot] pid={proc.pid}"})
    with job._lock:
        job.state = "running"
    for raw in iter(proc.stdout.readline, ""):
        line = raw.rstrip("\n")
        if not line:
            continue
        job.q.put({"type": "log", "line": line})
        low = line.lower()
        if "press enter" in low or "press enter here" in low:
            with job._lock:
                job.state = "awaiting_enter"
            job.q.put({"type": "awaiting_enter"})
    rc = proc.wait()
    if rc == 0:
        _clear_stale_marker()
    with job._lock:
        job.exit_code = rc
        job.state = "done" if rc == 0 else "failed"
    job.q.put({"type": "done", "exit_code": rc, "cookies": status()})


def start_refresh() -> Job:
    if not SCRIPT_PATH.exists():
        raise FileNotFoundError(f"missing {SCRIPT_PATH}")
    python_exe = (Path(".venv/bin/python").resolve()
                  if Path(".venv/bin/python").exists() else sys.executable)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [str(python_exe), str(SCRIPT_PATH)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
        env=env,
    )
    job = Job(id=uuid.uuid4().hex[:12], proc=proc, q=Queue())
    with _jobs_lock:
        _JOBS[job.id] = job
    threading.Thread(target=_pump_stdout, args=(job,), daemon=True).start()
    return job


def confirm(job_id: str) -> dict:
    job = get(job_id)
    if not job:
        return {"ok": False, "error": "unknown job"}
    if job.state == "done":
        return {"ok": True, "note": "already complete"}
    if job.proc.stdin is None:
        return {"ok": False, "error": "no stdin"}
    try:
        job.proc.stdin.write("\n")
        job.proc.stdin.flush()
        return {"ok": True}
    except (OSError, BrokenPipeError) as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def cancel(job_id: str) -> dict:
    job = get(job_id)
    if not job:
        return {"ok": False, "error": "unknown job"}
    try:
        job.proc.terminate()
    except OSError:
        pass
    with job._lock:
        job.state = "cancelled"
    job.q.put({"type": "cancelled"})
    return {"ok": True}


def drain_events(job_id: str, timeout: float = 1.0) -> list[dict]:
    job = get(job_id)
    if not job:
        return [{"type": "error", "error": "unknown job"}]
    out: list[dict] = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            out.append(job.q.get(timeout=max(0.05, deadline - time.time())))
        except Empty:
            break
        if out[-1].get("type") == "done":
            break
    return out
