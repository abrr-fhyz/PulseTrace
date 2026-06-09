"""Scheduling / orchestration knobs, read from env with safe defaults.

Single config surface for the orchestration layer. Import these constants;
never read the raw env vars elsewhere so the defaults stay in one place.
"""
from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    """Read an int env var, falling back to ``default`` on missing/garbage."""
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    """Read a float env var, falling back to ``default`` on missing/garbage."""
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


MAX_RETRIES: int = _int("AGENT_MAX_RETRIES", 3)
RETRY_BACKOFF_SECS: int = _int("AGENT_RETRY_BACKOFF_SECS", 30)
ENGAGEMENT_THRESHOLD: float = _float("AGENT_ENGAGEMENT_THRESHOLD", 0.75)
N8N_WEBHOOK_BASE_URL: str = os.environ.get("N8N_WEBHOOK_BASE_URL", "http://localhost:5678")
N8N_RECRAWL_CRON: str = os.environ.get("N8N_RECRAWL_CRON", "0 */6 * * *")

# Squash constant: raw influence -> (0, 1) via 1 - exp(-raw / SCALE).
# Higher SCALE => need more engagement to trip ENGAGEMENT_THRESHOLD.
ENGAGEMENT_SQUASH_SCALE: float = _float("AGENT_ENGAGEMENT_SQUASH_SCALE", 3.0)
