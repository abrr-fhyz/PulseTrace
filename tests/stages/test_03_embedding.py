"""Stage 3: embedding providers return normalized vectors.

Verifies each embedding-capable provider end-to-end through `embed_texts`,
including the on-disk cache write/read round-trip.
"""
from __future__ import annotations
import os

import numpy as np
import pytest
import requests

from .conftest import EMBED_PROVIDERS, has_key, write_stage_artifact, shared_state  # noqa: F401


def _ollama_local_up() -> bool:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        return requests.get(f"{host}/api/tags", timeout=3).status_code == 200
    except Exception:
        return False


@pytest.mark.parametrize("provider", EMBED_PROVIDERS)
def test_embed_provider_returns_unit_vectors(provider, monkeypatch, tmp_path, shared_state):
    if provider == "ollama":
        if not _ollama_local_up():
            pytest.skip("local Ollama not running")
    elif not has_key(provider):
        pytest.skip(f"no key for {provider}")

    monkeypatch.setenv("PULSETRACE_BACKEND", provider)
    monkeypatch.setenv("PULSETRACE_EMBED_BACKEND", provider)

    from lib import embed as embed_mod
    monkeypatch.setattr(embed_mod, "CACHE_PATH", tmp_path / "cache.jsonl")

    texts = ["donald trump rally in buffalo", "buffalo bills football"]
    try:
        arr = embed_mod.embed_texts(texts)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        write_stage_artifact(f"stage03_{provider}_error.json",
                             {"provider": provider, "error": msg})
        low = msg.lower()
        for marker in ("429", "rate", "quota", "resource_exhausted",
                       "402", "payment", "401", "403"):
            if marker in low:
                pytest.skip(f"{provider} embed: {msg[:160]}")
        pytest.fail(f"{provider} embed raised: {msg}")

    assert isinstance(arr, np.ndarray)
    assert arr.shape[0] == 2 and arr.shape[1] > 8, f"{provider}: bad shape {arr.shape}"
    norms = np.linalg.norm(arr, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-3), f"{provider}: not unit-normalized {norms}"
    assert (embed_mod.CACHE_PATH).exists()

    write_stage_artifact(f"stage03_{provider}_ok.json",
                         {"provider": provider, "dim": int(arr.shape[1])})
    shared_state.setdefault("working_embed_providers", []).append(provider)
