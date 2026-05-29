"""Loader for `.env.api_keys` (lowercase=value file with raw provider keys).

Maps file keys onto canonical env vars used by `lib.backend`. Safe to call
multiple times; never overwrites a value already set in os.environ.
"""
from __future__ import annotations
import os
from pathlib import Path


FILE_TO_ENV = {
    "huggingface_token":  "HUGGINGFACE_TOKEN",
    "gemini_api_key":     "GEMINI_API_KEY",
    "openrouter_api_key": "OPENROUTER_API_KEY",
    "ollama_api_key":     "OLLAMA_API_KEY",
    "groq_api_key":       "GROQ_API_KEY",
    "pollen_api_key":     "POLLEN_API_KEY",
    "LLM7_api_key":       "LLM7_API_KEY",
}


def load(path: str | Path = ".env.api_keys") -> None:
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        canonical = FILE_TO_ENV.get(k, k.upper())
        os.environ.setdefault(canonical, v)
