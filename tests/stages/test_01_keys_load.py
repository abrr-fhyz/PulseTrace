"""Stage 1: `.env.api_keys` loads -> canonical env vars populated."""
from __future__ import annotations
import os

import pytest

from .conftest import CHAT_PROVIDERS


def test_keys_loader_idempotent():
    from lib import keys
    before = dict(os.environ)
    keys.load()
    keys.load()
    # No spurious deletions.
    for k, v in before.items():
        assert os.environ.get(k) == v


@pytest.mark.parametrize("env_var", [
    "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
    "LLM7_API_KEY", "HUGGINGFACE_TOKEN", "POLLEN_API_KEY",
])
def test_each_provider_has_key(env_var):
    if not os.environ.get(env_var):
        pytest.skip(f"{env_var} not set in .env.api_keys")
    val = os.environ[env_var]
    assert len(val) >= 10, f"{env_var} suspiciously short"


def test_provider_registry_complete():
    from lib import backend
    for name in CHAT_PROVIDERS:
        assert name in backend.PROVIDERS, f"missing provider {name}"
        p = backend.PROVIDERS[name]
        assert p.chat_model
        assert p.key_env
