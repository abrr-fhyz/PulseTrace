from __future__ import annotations

import importlib

import pytest

from lib.orchestration import config

pytestmark = pytest.mark.unit


def test_defaults_present() -> None:
    assert config.MAX_RETRIES == 3
    assert config.RETRY_BACKOFF_SECS == 30
    assert config.ENGAGEMENT_THRESHOLD == 0.75
    assert config.N8N_WEBHOOK_BASE_URL.startswith("http")
    assert config.N8N_RECRAWL_CRON == "0 */6 * * *"


def test_int_garbage_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MAX_RETRIES", "not-a-number")
    reloaded = importlib.reload(config)
    assert reloaded.MAX_RETRIES == 3


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MAX_RETRIES", "7")
    monkeypatch.setenv("AGENT_ENGAGEMENT_THRESHOLD", "0.5")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.MAX_RETRIES == 7
        assert reloaded.ENGAGEMENT_THRESHOLD == 0.5
    finally:
        monkeypatch.delenv("AGENT_MAX_RETRIES")
        monkeypatch.delenv("AGENT_ENGAGEMENT_THRESHOLD")
        importlib.reload(config)
