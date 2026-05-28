"""Live Ollama backend tests.

Requires:
  PULSETRACE_BACKEND=ollama
  Ollama serving at OLLAMA_HOST (default http://localhost:11434)
  Chat model: OLLAMA_CHAT_MODEL (default llama3.2:3b)
  Embed model: OLLAMA_EMBED_MODEL (default nomic-embed-text)

Run with:
  PULSETRACE_BACKEND=ollama .venv/bin/python -m pytest tests/test_ollama_backend.py -v -m slow
"""
from __future__ import annotations
import os
import pytest
import requests
import numpy as np

pytestmark = pytest.mark.slow


def _ollama_up() -> bool:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        r = requests.get(f"{host}/api/tags", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


_OLLAMA_REQUIRED = pytest.mark.skipif(
    os.environ.get("PULSETRACE_BACKEND", "").lower() != "ollama",
    reason="set PULSETRACE_BACKEND=ollama to run",
)
_OLLAMA_UP = pytest.mark.skipif(not _ollama_up(), reason="Ollama not reachable")


@_OLLAMA_REQUIRED
@_OLLAMA_UP
def test_chat_json_returns_dict():
    from lib.llm import chat_json
    out = chat_json(
        'Respond strictly as JSON {"answer": <number>}.',
        "What is 2 plus 2? Respond as JSON.",
        max_tokens=200,
    )
    assert isinstance(out, dict)
    assert "answer" in out
    val = out["answer"]
    assert val == 4 or str(val).strip() == "4" or "4" in str(val)


@_OLLAMA_REQUIRED
@_OLLAMA_UP
def test_chat_json_handles_cluster_label_prompt():
    from lib.label import label_cluster
    samples = [
        "Tried Llama 3 today, it runs surprisingly fast on my laptop.",
        "Ollama is great for running local LLMs without an API key.",
        "Local inference is finally usable for hobby projects.",
    ]
    meta = label_cluster(samples)
    assert isinstance(meta, dict)
    assert "label" in meta and isinstance(meta["label"], str)
    assert len(meta["label"]) > 0


@_OLLAMA_REQUIRED
@_OLLAMA_UP
def test_embed_returns_normalized_matrix():
    from lib.embed import embed_texts
    arr = embed_texts(["hello world", "machine learning is fun"])
    assert arr.shape[0] == 2
    assert arr.shape[1] > 0
    norms = np.linalg.norm(arr, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-3)


@_OLLAMA_REQUIRED
@_OLLAMA_UP
def test_embed_cache_hits_on_repeat(tmp_path, monkeypatch):
    from lib import embed as embmod
    monkeypatch.setattr(embmod, "CACHE_PATH", tmp_path / "cache.jsonl")
    a = embmod.embed_texts(["consistent text"])
    b = embmod.embed_texts(["consistent text"])
    assert np.allclose(a, b)
    # cache file written + non-empty
    assert (tmp_path / "cache.jsonl").exists()
    assert (tmp_path / "cache.jsonl").stat().st_size > 0


@_OLLAMA_REQUIRED
@_OLLAMA_UP
def test_clustering_over_real_embeddings():
    from lib.embed import embed_texts
    from lib.cluster import cluster_embeddings
    texts = [
        "Pythons are non-venomous constrictor snakes.",
        "Boas are similar to pythons but give birth to live young.",
        "Anacondas live in the swamps of South America.",
        "Italian pasta is delicious especially carbonara.",
        "Risotto is a creamy rice dish from northern Italy.",
        "Margherita pizza uses fresh basil and mozzarella.",
    ]
    emb = embed_texts(texts)
    labels = cluster_embeddings(emb, min_cluster_size=2)
    valid = labels[labels >= 0]
    assert len(set(valid.tolist())) >= 2
