"""Embedding client with sha1-keyed JSONL cache.

Routes through `backend.embed_provider()`. Local Ollama keeps its native
`/api/embeddings` path; everything else uses the OpenAI-compatible
`embeddings.create` endpoint.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import numpy as np
import requests

from . import backend


CACHE_PATH = Path("data/embed_cache.jsonl")
DEFAULT_EMBED_DIM = backend.PROVIDERS["gemini"].embed_dim or 768


def _backend_tag() -> str:
    if backend.is_ollama():
        return f"ollama:{backend.OLLAMA_EMBED_MODEL}"
    p = backend.embed_provider()
    return f"{p.name}:{p.embed_model}"


def _key(text: str) -> str:
    return hashlib.sha1(f"{_backend_tag()}::{text}".encode("utf-8")).hexdigest()


_KEY_RE = re.compile(r'"k"\s*:\s*"([0-9a-f]{40})"')


def _peek_key(line: str) -> str | None:
    # The writer emits {"k": "<sha1>", "v": [...]} with the key first, so the
    # sha1 lives in the first ~60 chars. Matching it without json-parsing the
    # whole line lets us skip the ~60KB float vector on rows we don't need.
    m = _KEY_RE.search(line, 0, 64)
    return m.group(1) if m else None


def _load_cached(wanted: set[str]) -> dict[str, list[float]]:
    if not wanted or not CACHE_PATH.exists():
        return {}
    found: dict[str, list[float]] = {}
    with CACHE_PATH.open() as f:
        for line in f:
            k = _peek_key(line)
            if k is None or k not in wanted or k in found:
                continue
            try:
                found[k] = json.loads(line)["v"]
            except Exception:
                continue
            if len(found) == len(wanted):
                break
    return found


def _append_cache(rows: list[tuple[str, list[float]]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("a") as f:
        for k, v in rows:
            f.write(json.dumps({"k": k, "v": v}) + "\n")


def _embed_openai_compat(p: backend.Provider, texts: list[str], batch: int) -> list[list[float]]:
    from openai import OpenAI
    kwargs: dict[str, Any] = {"api_key": os.environ.get(p.key_env) or "EMPTY"}
    if p.base_url:
        kwargs["base_url"] = p.base_url
    client = OpenAI(**kwargs)
    out: list[list[float]] = []
    for start in range(0, len(texts), batch):
        chunk = [t[:8000] for t in texts[start:start + batch]]
        resp = client.embeddings.create(model=p.embed_model, input=chunk)
        out.extend(d.embedding for d in resp.data)
    return out


def _embed_ollama_native(texts: list[str]) -> list[list[float]]:
    url = f"{backend.OLLAMA_HOST}/api/embeddings"
    headers: dict[str, str] = {}
    key = os.environ.get("OLLAMA_API_KEY", "")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    out: list[list[float]] = []
    for t in texts:
        r = requests.post(
            url,
            json={"model": backend.OLLAMA_EMBED_MODEL, "prompt": t[:8000]},
            headers=headers,
            timeout=backend.OLLAMA_EMBED_TIMEOUT,
        )
        r.raise_for_status()
        out.append(r.json()["embedding"])
    return out


def embed_texts(texts: list[str], batch: int = 100) -> np.ndarray:
    if not texts:
        dim = _probe_dim_or_zero() or DEFAULT_EMBED_DIM
        return np.zeros((0, max(dim, 1)), dtype=np.float32)

    keys = [_key(t) for t in texts]
    cache = _load_cached(set(keys))

    # Collapse duplicate texts to a single embedding call: identical strings
    # share a key, so embedding them more than once just burns tokens and
    # appends duplicate cache rows.
    missing: dict[str, str] = {}
    for i, k in enumerate(keys):
        if k not in cache and k not in missing:
            missing[k] = texts[i]

    if missing:
        miss_keys = list(missing)
        chunk_texts = [missing[k] for k in miss_keys]
        if backend.is_ollama():
            vectors = _embed_ollama_native(chunk_texts)
        else:
            vectors = _embed_openai_compat(backend.embed_provider(), chunk_texts, batch)
        new_rows = list(zip(miss_keys, vectors))
        for k, v in new_rows:
            cache[k] = v
        _append_cache(new_rows)

    arr = np.array([cache[k] for k in keys], dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    arr = arr / np.clip(norms, 1e-9, None)
    return arr


def _probe_dim_or_zero() -> int:
    if not backend.is_ollama():
        p = backend.embed_provider()
        return p.embed_dim or DEFAULT_EMBED_DIM
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
