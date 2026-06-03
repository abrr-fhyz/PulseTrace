"""Shareable run export: signed tokens + run-dir tarballs.

No auth system exists; the HMAC signature only stops URL guessing/tampering.
Tokens embed run_id + expiry so a leaked link self-expires.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import tarfile
import time
from pathlib import Path

from lib import store

DEFAULT_TTL_SECONDS = 7 * 24 * 3600


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _sign(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(digest)


def make_token(run_id: str, expires_at: int, secret: str) -> str:
    body = {"rid": run_id, "exp": int(expires_at)}
    payload = _b64encode(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    return f"{payload}.{_sign(payload, secret)}"


def verify_token(token: str, secret: str, now: int | None = None) -> str | None:
    if not token or "." not in token:
        return None
    payload, _, sig = token.partition(".")
    if not payload or not sig:
        return None
    expected = _sign(payload, secret)
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        body = json.loads(_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    run_id = body.get("rid")
    exp = body.get("exp")
    if not isinstance(run_id, str) or not isinstance(exp, int):
        return None
    current = int(time.time()) if now is None else now
    if current >= exp:
        return None
    return run_id


def bundle_run(run_id: str, dest_dir: str = "/tmp") -> str:
    src = store.ROOT / run_id
    if not src.is_dir():
        raise FileNotFoundError(f"run dir not found: {src}")
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"pulsetrace-{run_id}.tar.gz"
    with tarfile.open(out, "w:gz") as tf:
        tf.add(src, arcname=run_id)
    return str(out)
