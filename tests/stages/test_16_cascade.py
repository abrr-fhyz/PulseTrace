"""Stage 16: provider cascade dispatcher.

Validates that LLM calls spread across every credentialed provider — no single
account eats the whole budget — and that retryable failures (quota/auth/404)
fall through to the next provider instead of crashing the agent.

Pure-logic tests for `lib.dispatch`; integration test that monkeypatches the
HTTP transport so we never hit real APIs from this file.
"""
from __future__ import annotations
import os
from unittest.mock import patch

import pytest

from lib import backend, dispatch


@pytest.fixture(autouse=True)
def _reset_counters():
    """Each test starts from a clean rotation state."""
    dispatch._stage_counter.clear()
    yield
    dispatch._stage_counter.clear()


@pytest.fixture
def fake_keys(monkeypatch):
    """Pretend every cloud provider has a working API key."""
    monkeypatch.delenv("PULSETRACE_BACKEND", raising=False)
    monkeypatch.delenv("PULSETRACE_CHAT_CASCADE", raising=False)
    for prov in dispatch.DEFAULT_CASCADE:
        p = backend.PROVIDERS.get(prov)
        if p and p.name != "ollama":
            monkeypatch.setenv(p.key_env, "fake-key")
    yield


def test_cascade_only_returns_providers_with_credentials(monkeypatch):
    monkeypatch.delenv("PULSETRACE_BACKEND", raising=False)
    monkeypatch.delenv("PULSETRACE_CHAT_CASCADE", raising=False)
    for prov in dispatch.DEFAULT_CASCADE:
        p = backend.PROVIDERS.get(prov)
        if p and p.name != "ollama":
            monkeypatch.delenv(p.key_env, raising=False)
    # Only ollama (which is always considered "available" locally) should remain.
    chain = dispatch.cascade_for_stage("seed")
    names = [p.name for p in chain]
    assert "ollama" in names
    assert all(n in {"ollama"} for n in names)


def test_forced_backend_disables_cascade(monkeypatch, fake_keys):
    monkeypatch.setenv("PULSETRACE_BACKEND", "groq")
    chain = dispatch.cascade_for_stage("seed")
    assert [p.name for p in chain] == ["groq"]


def test_rotation_advances_per_call(fake_keys):
    first = dispatch.cascade_for_stage("seed")[0].name
    second = dispatch.cascade_for_stage("seed")[0].name
    third = dispatch.cascade_for_stage("seed")[0].name
    assert first != second or second != third  # at least one rotation step


def test_different_stages_start_at_different_providers(fake_keys):
    """seed/next/label/stance/rag have distinct offsets so the same first
    request of each stage hits a different provider."""
    firsts = {
        s: dispatch.cascade_for_stage(s)[0].name
        for s in ("seed", "next", "label", "stance", "rag")
    }
    assert len(set(firsts.values())) >= 3, firsts


def test_cascade_override_via_env(monkeypatch, fake_keys):
    monkeypatch.setenv("PULSETRACE_CHAT_CASCADE", "llm7,groq")
    names = [p.name for p in dispatch.cascade_for_stage("seed")]
    assert set(names) == {"llm7", "groq"}


@pytest.mark.parametrize("msg", [
    "Error code: 429 rate limit exceeded",
    "Error code: 404 - models/gemini-1.5-flash is not found",
    "401 Unauthorized",
    "RESOURCE_EXHAUSTED quota",
    "Connection timeout",
    "503 Service Unavailable",
])
def test_is_retryable_recognises_provider_errors(msg):
    assert dispatch.is_retryable(Exception(msg)) is True


def test_is_retryable_skips_logic_bugs():
    assert dispatch.is_retryable(KeyError("missing_field")) is False
    assert dispatch.is_retryable(ValueError("bad arg")) is False


def test_chat_json_falls_through_to_next_provider(fake_keys, monkeypatch):
    """First two providers raise retryable errors; third succeeds. chat_json
    must return the third provider's payload, not bubble the first error."""
    from lib import llm

    monkeypatch.setenv("PULSETRACE_CHAT_CASCADE", "groq,openrouter,llm7")
    monkeypatch.delenv("PULSETRACE_BACKEND", raising=False)

    calls: list[str] = []

    def fake_call(provider, system, user, max_tokens):
        calls.append(provider.name)
        if provider.name == "groq":
            raise RuntimeError("Error code: 429 quota")
        if provider.name == "openrouter":
            raise RuntimeError("Error code: 401 unauthorized")
        return {"ok": True, "provider": provider.name}

    with patch.object(llm, "_chat_openai_compat", side_effect=fake_call):
        out = llm.chat_json_cascade("sys", "user", stage="seed")

    assert out == {"ok": True, "provider": "llm7"}
    assert calls == ["groq", "openrouter", "llm7"]


def test_chat_json_reraises_when_all_providers_fail(fake_keys, monkeypatch):
    from lib import llm

    monkeypatch.setenv("PULSETRACE_CHAT_CASCADE", "groq,llm7")
    monkeypatch.delenv("PULSETRACE_BACKEND", raising=False)

    def boom(provider, system, user, max_tokens):
        raise RuntimeError("429 rate limit")

    with patch.object(llm, "_chat_openai_compat", side_effect=boom):
        with pytest.raises(RuntimeError, match="429"):
            llm.chat_json_cascade("sys", "user", stage="seed")


def test_chat_json_non_retryable_does_not_advance(fake_keys, monkeypatch):
    """A caller-side bug (e.g. KeyError) shouldn't burn through every key."""
    from lib import llm

    monkeypatch.setenv("PULSETRACE_CHAT_CASCADE", "groq,openrouter,llm7")
    monkeypatch.delenv("PULSETRACE_BACKEND", raising=False)
    calls: list[str] = []

    def fake_call(provider, system, user, max_tokens):
        calls.append(provider.name)
        raise KeyError("bug")

    with patch.object(llm, "_chat_openai_compat", side_effect=fake_call):
        with pytest.raises(KeyError):
            llm.chat_json_cascade("sys", "user", stage="seed")

    assert len(calls) == 1


def test_stage_default_keyword_is_optional(fake_keys, monkeypatch):
    """Legacy call sites that omit `stage` must still work."""
    from lib import llm

    monkeypatch.setenv("PULSETRACE_CHAT_CASCADE", "groq")
    monkeypatch.delenv("PULSETRACE_BACKEND", raising=False)

    with patch.object(llm, "_chat_openai_compat",
                      return_value={"ok": True}):
        assert llm.chat_json_cascade("sys", "user") == {"ok": True}
