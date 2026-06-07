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
