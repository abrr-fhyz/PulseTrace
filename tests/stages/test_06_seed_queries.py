"""Stage 6: agent seed-query + next-action LLM helpers."""
from __future__ import annotations
import os

import pytest

from .conftest import TOPIC, CHAT_PROVIDERS, has_key, write_stage_artifact


def _first_working_provider() -> str | None:
    for p in CHAT_PROVIDERS:
        if has_key(p):
            return p
    return None


def test_seed_queries_for_topic(monkeypatch):
    provider = _first_working_provider()
    if not provider:
        pytest.skip("no chat providers configured")
    monkeypatch.setenv("PULSETRACE_BACKEND", provider)

    from lib import agent
    seeds = agent._llm_seed(TOPIC)
    write_stage_artifact("stage06_seeds.json", {"provider": provider, "seeds": seeds})
    assert isinstance(seeds, list)
    assert 1 <= len(seeds) <= 5
    for s in seeds:
        assert isinstance(s, str) and s.strip()


def test_next_action_decision(monkeypatch):
    provider = _first_working_provider()
    if not provider:
        pytest.skip("no chat providers configured")
    monkeypatch.setenv("PULSETRACE_BACKEND", provider)

    from lib import agent
    decision = agent._llm_next(TOPIC, ["Trump rally coverage", "Buffalo local politics"])
    write_stage_artifact("stage06_next.json",
                         {"provider": provider, "decision": decision})
    assert isinstance(decision, dict)
    assert decision.get("action") in ("stop", "expand")
    if decision["action"] == "expand":
        assert isinstance(decision.get("queries"), list)
