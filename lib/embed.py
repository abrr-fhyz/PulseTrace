"""Embedding client with sha1-keyed JSONL cache. Dispatches openai or ollama."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import numpy as np
import requests

from . import backend


CACHE_PATH = Path("data/embed_cache.jsonl")
OPENAI_MODEL = "text-embedding-3-small"
OPENAI_DIM = 1536


def _backend_tag() -> str:
    if backend.is_ollama():
        return f"ollama:{backend.OLLAMA_EMBED_MODEL}"
    return f"openai:{OPENAI_MODEL}"


def _key(text: str) -> str:
    salted = f"{_backend_tag()}::{text}"
    return hashlib.sha1(salted.encode("utf-8")).hexdigest()


def _load_cache() -> dict[str, list[float]]:
    if not CACHE_PATH.exists():
        return {}
    cache: dict[str, list[float]] = {}
    with CACHE_PATH.open() as f:
        for line in f:
            try:
                row = json.loads(line)
                cache[row["k"]] = row["v"]
            except Exception:
                continue
    return cache


def _append_cache(rows: list[tuple[str, list[float]]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("a") as f:
        for k, v in rows:
            f.write(json.dumps({"k": k, "v": v}) + "\n")


def _embed_openai(texts: list[str], batch: int) -> list[list[float]]:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    out: list[list[float]] = []
    for start in range(0, len(texts), batch):
        chunk = [t[:8000] for t in texts[start:start + batch]]
        resp = client.embeddings.create(model=OPENAI_MODEL, input=chunk)
        out.extend(d.embedding for d in resp.data)
    return out


def _embed_ollama(texts: list[str]) -> list[list[float]]:
    url = f"{backend.OLLAMA_HOST}/api/embeddings"
    out: list[list[float]] = []
    for t in texts:
        r = requests.post(
            url,
            json={"model": backend.OLLAMA_EMBED_MODEL, "prompt": t[:8000]},
            timeout=backend.OLLAMA_EMBED_TIMEOUT,
        )
        r.raise_for_status()
        out.append(r.json()["embedding"])
    return out


def embed_texts(texts: list[str], batch: int = 100) -> np.ndarray:
    if not texts:
        dim = OPENAI_DIM if backend.is_openai() else _probe_dim_or_zero()
        return np.zeros((0, max(dim, 1)), dtype=np.float32)

    cache = _load_cache()
    keys = [_key(t) for t in texts]
    missing_idx = [i for i, k in enumerate(keys) if k not in cache]

    if missing_idx:
        chunk_texts = [texts[i] for i in missing_idx]
        vectors = (_embed_ollama(chunk_texts) if backend.is_ollama()
                   else _embed_openai(chunk_texts, batch))
        new_rows: list[tuple[str, list[float]]] = []
        for i, v in zip(missing_idx, vectors):
            cache[keys[i]] = v
            new_rows.append((keys[i], v))
        _append_cache(new_rows)

    arr = np.array([cache[k] for k in keys], dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    arr = arr / np.clip(norms, 1e-9, None)
    return arr


def _probe_dim_or_zero() -> int:
    """Best-effort: ask Ollama for the embed model's dim by embedding one token."""
    if not backend.is_ollama():
        return OPENAI_DIM
    try:
        r = requests.post(
            f"{backend.OLLAMA_HOST}/api/embeddings",
            json={"model": backend.OLLAMA_EMBED_MODEL, "prompt": "."},
            timeout=backend.OLLAMA_EMBED_TIMEOUT,
        )
        r.raise_for_status()
        return len(r.json().get("embedding") or [])
    except Exception:
        return 0
