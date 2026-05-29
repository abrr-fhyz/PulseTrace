"""Stage 7: cluster + label + sentiment on real embedded HN posts."""
from __future__ import annotations
import os

import numpy as np
import pytest
import requests

from .conftest import TOPIC, CHAT_PROVIDERS, EMBED_PROVIDERS, has_key, write_stage_artifact


def _pick_chat() -> str | None:
    for p in CHAT_PROVIDERS:
        if has_key(p):
            return p
    return None


def _pick_embed() -> str | None:
    # Prefer local Ollama (cheap, no quota), then OpenAI, then Gemini.
    try:
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        if requests.get(f"{host}/api/tags", timeout=3).status_code == 200:
            return "ollama"
    except Exception:
        pass
    if has_key("openai"):
        return "openai"
    if has_key("gemini"):
        return "gemini"
    return None


def test_cluster_label_pipeline(monkeypatch, tmp_path):
    chat = _pick_chat()
    embed = _pick_embed()
    if not chat:
        pytest.skip("no chat provider")
    if not embed:
        pytest.skip("no embed provider")

    monkeypatch.setenv("PULSETRACE_BACKEND", chat)
    monkeypatch.setenv("PULSETRACE_EMBED_BACKEND", embed)

    from lib import embed as embed_mod
    monkeypatch.setattr(embed_mod, "CACHE_PATH", tmp_path / "cache.jsonl")

    from lib.connectors.hn import HNConnector
    from lib.embed import embed_texts
    from lib.cluster import cluster_embeddings, centroids
    from lib.label import label_cluster
    from lib.stance import cluster_sentiment

    posts = HNConnector().fetch(TOPIC, limit=25)
    if len(posts) < 6:
        pytest.skip(f"only {len(posts)} HN posts — too few for clustering")

    emb = embed_texts([p.text for p in posts])
    assert emb.shape == (len(posts), emb.shape[1])

    labels = cluster_embeddings(emb)
    assert labels.shape == (len(posts),)
    cents = centroids(emb, labels)
    assert cents, "no cluster centroids produced"

    summary = []
    for cid, c in cents.items():
        members = [posts[i] for i, lab in enumerate(labels) if lab == cid]
        meta = label_cluster([m.text for m in members[:8]])
        sent = cluster_sentiment(meta["label"], [m.text for m in members])
        assert isinstance(meta.get("label"), str) and meta["label"]
        assert 0.99 <= sent["pos"] + sent["neu"] + sent["neg"] <= 1.01
        summary.append({"id": int(cid), "label": meta["label"],
                        "n": len(members), "sentiment": sent})

    write_stage_artifact("stage07_clusters.json", {
        "chat_provider": chat, "embed_provider": embed,
        "n_posts": len(posts), "clusters": summary,
    })
