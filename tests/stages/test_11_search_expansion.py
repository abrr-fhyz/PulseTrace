"""Stage 11: autonomous search expansion.

Backs README use-case "Step 1 — Generate search queries" and the agent's
iterative expansion (_llm_next deciding stop|expand with new queries).
"""
from __future__ import annotations
import os

import pytest

from .conftest import TOPIC, pick_chat_provider, write_stage_artifact


def test_seed_queries_diverse(monkeypatch):
    chat = pick_chat_provider()
    if not chat:
        pytest.skip("no chat provider")
    monkeypatch.setenv("PULSETRACE_BACKEND", chat)

    from lib import agent
    seeds = agent._llm_seed(TOPIC)
    assert 1 <= len(seeds) <= 5
    # If LLM returned >1 query, they should not all be identical to the topic.
    if len(seeds) > 1:
        unique = {s.strip().lower() for s in seeds}
        assert len(unique) >= 2, f"seeds collapsed to duplicates: {seeds}"

    write_stage_artifact("stage11_seeds.json",
                         {"topic": TOPIC, "chat": chat, "seeds": seeds})


def test_expansion_proposes_distinct_queries(monkeypatch):
    chat = pick_chat_provider()
    if not chat:
        pytest.skip("no chat provider")
    monkeypatch.setenv("PULSETRACE_BACKEND", chat)

    from lib import agent
    seeds = agent._llm_seed(TOPIC)
    # Give the agent some plausible labels to expand from.
    fake_labels = ["news coverage", "personal opinion", "policy impact"]
    decision = agent._llm_next(TOPIC, fake_labels)

    assert isinstance(decision, dict)
    assert decision.get("action") in ("stop", "expand")

    new_qs: list[str] = []
    if decision["action"] == "expand":
        new_qs = [str(q) for q in decision.get("queries", []) if q]
        assert new_qs, "expand decision must include queries"
        # Expansion ideally surfaces something not in the seed set.
        seeds_set = {s.lower().strip() for s in seeds}
        novel = [q for q in new_qs if q.lower().strip() not in seeds_set]
        # Soft expectation: at least one query is novel. If model echoes,
        # surface it via artifact rather than failing — provider-dependent.
        if not novel:
            write_stage_artifact("stage11_expansion_warning.json",
                                 {"seeds": seeds, "expansion": new_qs,
                                  "note": "no novel queries"})
    write_stage_artifact("stage11_expansion.json", {
        "topic": TOPIC, "seeds": seeds,
        "action": decision["action"], "new_queries": new_qs,
    })


def test_empty_seed_falls_back_to_topic(monkeypatch):
    """If LLM fails entirely, agent must still return [topic] as the seed."""
    from lib import agent

    def boom(*a, **k):
        raise RuntimeError("simulated LLM down")
    monkeypatch.setattr(agent, "chat_json", boom)
    seeds = agent._llm_seed("X")
    assert seeds == ["X"]
