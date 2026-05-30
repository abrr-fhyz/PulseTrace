"""Stage-aware provider cascade for LLM chat.

Distributes LLM calls across every provider with a working key so no single
account exhausts its free-tier budget. Each stage (seed, next, label, stance,
rag) gets a different rotation offset, and the per-stage counter advances on
every call. Failures (rate-limit, quota, auth, model-not-found, parse) skip
to the next provider in the cascade.

Config knobs:
  PULSETRACE_BACKEND        force a single provider, disables cascade
  PULSETRACE_CHAT_CASCADE   comma-list overriding default cascade order
"""
from __future__ import annotations
import os
import threading
from typing import Iterable

from . import backend


DEFAULT_CASCADE = [
    "gemini",
    "groq",
    "openrouter",
    "llm7",
    "huggingface",
    "pollen",
    "ollama",
]

STAGE_OFFSET = {
    "seed":   0,
    "next":   1,
    "label":  2,
    "stance": 3,
    "rag":    4,
    "default": 0,
}

_lock = threading.Lock()
_stage_counter: dict[str, int] = {}


def _has_credentials(p: backend.Provider) -> bool:
    if p.name == "ollama":
        return True
    return bool(os.environ.get(p.key_env))


def _configured_cascade() -> list[str]:
    raw = (os.environ.get("PULSETRACE_CHAT_CASCADE") or "").strip()
    if raw:
        wanted = [x.strip().lower() for x in raw.split(",") if x.strip()]
    else:
        wanted = DEFAULT_CASCADE
    return [n for n in wanted if n in backend.PROVIDERS]


def cascade_for_stage(stage: str) -> list[backend.Provider]:
    """Ordered provider list for this stage. Caller iterates until one succeeds."""
    forced = (os.environ.get("PULSETRACE_BACKEND") or "").lower().strip()
    if forced and forced in backend.PROVIDERS:
        return [backend.PROVIDERS[forced]]

    base = _configured_cascade()
    available = [n for n in base if _has_credentials(backend.PROVIDERS[n])]
    if not available:
        return [backend.PROVIDERS["gemini"]]

    with _lock:
        idx = _stage_counter.get(stage, STAGE_OFFSET.get(stage, 0))
        _stage_counter[stage] = idx + 1
    start = idx % len(available)
    ordered = available[start:] + available[:start]
    return [backend.PROVIDERS[n] for n in ordered]


def is_retryable(err: Exception) -> bool:
    """True if the error is provider-specific (quota/auth/model) and the next
    provider in the cascade might work. False for caller-side bugs."""
    msg = (str(err) or "").lower()
    markers = (
        "429", "rate", "quota", "resource_exhausted",
        "401", "403", "auth", "unauthorized", "forbidden",
        "402", "payment", "billing", "gated",
        "404", "not found", "model_not_found",
        "503", "502", "500", "overloaded", "unavailable",
        "timeout", "timed out",
    )
    return any(m in msg for m in markers)
