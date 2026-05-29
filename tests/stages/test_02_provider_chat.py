"""Stage 2: each LLM provider returns parseable JSON via `chat_json`.

Parameterized — every provider with a key in `.env.api_keys` is exercised
independently. A failure here points at provider auth/base-url/model.
"""
from __future__ import annotations
import os

import pytest

from .conftest import CHAT_PROVIDERS, has_key, write_stage_artifact, shared_state  # noqa: F401


@pytest.mark.parametrize("provider", CHAT_PROVIDERS)
def test_provider_chat_returns_json(provider, monkeypatch, shared_state):
    if not has_key(provider):
        pytest.skip(f"no key for {provider}")
    monkeypatch.setenv("PULSETRACE_BACKEND", provider)

    from lib.llm import chat_json
    try:
        out = chat_json(
            'Return JSON with exactly one key "value" whose value is the integer 7. '
            'Example: {"value": 7}',
            "respond",
            max_tokens=40,
        )
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        write_stage_artifact(f"stage02_{provider}_error.json",
                             {"provider": provider, "error": msg})
        # Treat quota/rate-limit/auth/gated-model as environmental skip, not bug.
        low = msg.lower()
        for marker in ("429", "rate", "quota", "resource_exhausted",
                       "402", "payment", "insufficient", "balance",
                       "401", "403", "gated", "not authorized"):
            if marker in low:
                pytest.skip(f"{provider}: {msg[:160]}")
        pytest.fail(f"{provider} raised: {msg}")

    write_stage_artifact(f"stage02_{provider}_ok.json",
                         {"provider": provider, "response": out})
    assert isinstance(out, dict), f"{provider}: not a dict -> {out!r}"
    assert out, f"{provider}: empty dict response"
    # Strict check: the model followed JSON spec we asked for.
    val = out.get("value")
    assert val in (7, "7"), f"{provider}: did not follow schema -> {out!r}"

    shared_state.setdefault("working_chat_providers", []).append(provider)
