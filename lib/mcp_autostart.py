"""Spawn the PulseTrace MCP server alongside the Flask app.

The MCP server (mcp_server.py) is normally launched on-demand over stdio by an
MCP client (Claude). For the running app — local `python server.py` or the
Docker/gunicorn image — we also want it reachable over HTTP so remote agents can
drive the same tools. This module brings it up once, idempotently.

Single-spawn guarantees:
  - port probe: if something already listens on the MCP port, skip (covers
    gunicorn's multiple workers and re-imports).
  - gated by PT_MCP_AUTOSTART (default on).
"""
from __future__ import annotations

import atexit
import logging
import os
import socket
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("pulsetrace.mcp_autostart")

_REPO = Path(__file__).resolve().parents[1]
_proc: subprocess.Popen | None = None

_TRUTHY = {"1", "true", "yes", "on"}


def _enabled() -> bool:
    return os.environ.get("PT_MCP_AUTOSTART", "1").strip().lower() in _TRUTHY


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def ensure_mcp_server() -> None:
    """Start the MCP server over streamable-http if not already running."""
    global _proc
    if not _enabled():
        log.info("MCP autostart disabled (PT_MCP_AUTOSTART)")
        return

    host = os.environ.get("PULSETRACE_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("PULSETRACE_MCP_PORT", "8000"))
    probe = "127.0.0.1" if host in ("0.0.0.0", "") else host

    if _port_open(probe, port):
        log.info("MCP server already listening on %s:%s — skipping spawn", probe, port)
        return
    if _proc is not None and _proc.poll() is None:
        return

    log_dir = _REPO / "data" / "event_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logfile = open(log_dir / "mcp_server.log", "ab", buffering=0)

    env = {
        **os.environ,
        "PULSETRACE_MCP_TRANSPORT": "streamable-http",
        "FASTMCP_HOST": host,
        "FASTMCP_PORT": str(port),
    }
    _proc = subprocess.Popen(
        [sys.executable, str(_REPO / "mcp_server.py")],
        cwd=str(_REPO),
        env=env,
        stdout=logfile,
        stderr=subprocess.STDOUT,
    )
    log.info("MCP server spawned (pid=%s) on http://%s:%s [streamable-http]",
             _proc.pid, host, port)
    atexit.register(_terminate)


def _terminate() -> None:
    if _proc is not None and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
