from __future__ import annotations
from unittest.mock import patch
from lib import agent


def test_seed_neutral_prompt_when_no_opinion():
    captured = {}

    def fake(system, user, **kw):
        captured["system"] = system
        return {"queries": ["a", "b"]}

    with patch("lib.agent.chat_json", side_effect=fake):
        qs = agent._llm_seed("Elden Ring", opinion=None)
    assert qs == ["a", "b"]
    assert "opinion" not in captured["system"].lower()


def test_seed_biases_pro_con_when_opinion_present():
    captured = {}

    def fake(system, user, **kw):
        captured["system"] = system
        captured["user"] = user
        return {"queries": ["a"]}

    with patch("lib.agent.chat_json", side_effect=fake):
        agent._llm_seed("Elden Ring", opinion="I want to play it")
    blob = (captured["system"] + captured["user"]).lower()
    assert "support" in blob and ("challeng" in blob or "against" in blob)


def test_seed_falls_back_to_topic_on_llm_error():
    with patch("lib.agent.chat_json", side_effect=RuntimeError("x")):
        assert agent._llm_seed("Topic", opinion=None) == ["Topic"]


def test_seed_caps_neutral_at_5_opinion_at_6():
    def fake(system, user, **kw):
        return {"queries": [f"q{i}" for i in range(10)]}

    with patch("lib.agent.chat_json", side_effect=fake):
        assert len(agent._llm_seed("T", opinion=None)) == 5
        assert len(agent._llm_seed("T", opinion="x")) == 6


def test_next_injects_opinion_framing():
    captured = {}

    def fake(system, user, **kw):
        captured["system"] = system
        return {"action": "expand", "queries": ["q"]}

    with patch("lib.agent.chat_json", side_effect=fake):
        agent._llm_next("Elden Ring", ["combat"], opinion="I want to play it")
    blob = captured["system"].lower()
    assert "opinion" in blob and ("support" in blob or "challenge" in blob)


def test_next_neutral_has_no_opinion():
    captured = {}

    def fake(system, user, **kw):
        captured["system"] = system
        return {"action": "stop", "queries": []}

    with patch("lib.agent.chat_json", side_effect=fake):
        agent._llm_next("Elden Ring", ["combat"], opinion=None)
    assert "opinion" not in captured["system"].lower()
