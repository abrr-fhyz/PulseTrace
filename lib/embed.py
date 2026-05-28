"""OpenAI embedding client with sha1-keyed JSONL cache."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import numpy as np


CACHE_PATH = Path("data/embed_cache.jsonl")
MODEL = "text-embedding-3-small"
DIM = 1536


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


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


def embed_texts(texts: list[str], batch: int = 100) -> np.ndarray:
    if not texts:
        return np.zeros((0, DIM), dtype=np.float32)
    cache = _load_cache()
    keys = [_key(t) for t in texts]
    missing_idx = [i for i, k in enumerate(keys) if k not in cache]

    if missing_idx:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        new_rows: list[tuple[str, list[float]]] = []
        for start in range(0, len(missing_idx), batch):
            chunk = missing_idx[start:start + batch]
            resp = client.embeddings.create(
                model=MODEL,
                input=[texts[i][:8000] for i in chunk],
            )
            for i, d in zip(chunk, resp.data):
                cache[keys[i]] = d.embedding
                new_rows.append((keys[i], d.embedding))
        _append_cache(new_rows)

    arr = np.array([cache[k] for k in keys], dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    arr = arr / np.clip(norms, 1e-9, None)
    return arr
