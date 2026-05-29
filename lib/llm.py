"""Strict-JSON chat wrapper with one retry.

OpenAI-compatible providers (openai, groq, openrouter, gemini, pollen, llm7,
huggingface, ollama-cloud) share one client path. Native local Ollama keeps a
direct `/api/chat` call for its `format=json` mode.
"""
from __future__ import annotations
import json
import os
from typing import Any

import requests
from openai import OpenAI

from . import backend


def _client_for(p: backend.Provider) -> OpenAI:
    api_key = os.environ.get(p.key_env) or "EMPTY"
    kwargs: dict[str, Any] = {"api_key": api_key}
    if p.base_url:
        kwargs["base_url"] = p.base_url
    if p.extra_headers:
        kwargs["default_headers"] = p.extra_headers
    return OpenAI(**kwargs)


def _chat_openai_compat(p: backend.Provider, system: str, user: str, max_tokens: int) -> Any:
    client = _client_for(p)
    last_err: Exception | None = None
    # Gemini's OpenAI shim historically chokes on response_format; try strict then plain.
    formats: list[dict[str, Any] | None] = [{"type": "json_object"}, None]
    for fmt in formats:
        for _ in range(2):
            try:
                kw: dict[str, Any] = dict(
                    model=p.chat_model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    max_tokens=max_tokens,
                    temperature=0.2,
                )
                if fmt is not None:
                    kw["response_format"] = fmt
                resp = client.chat.completions.create(**kw)
                raw = resp.choices[0].message.content or "{}"
                return json.loads(_strip_fence(raw))
            except json.JSONDecodeError as e:
                last_err = e
                continue
            except Exception as e:
                last_err = e
                break  # try next format
    raise last_err or ValueError(f"{p.name}: no parseable JSON")


def _strip_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip() or "{}"


def _chat_ollama_native(system: str, user: str, max_tokens: int) -> Any:
    url = f"{backend.OLLAMA_HOST}/api/chat"
    payload = {
        "model": backend.OLLAMA_CHAT_MODEL,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": max_tokens},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    headers: dict[str, str] = {}
    key = os.environ.get("OLLAMA_API_KEY", "")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    last_err: Exception | None = None
    for _ in range(2):
        try:
            r = requests.post(url, json=payload, headers=headers,
                              timeout=backend.OLLAMA_CHAT_TIMEOUT)
            r.raise_for_status()
        except Exception as e:
            last_err = e
            continue
        raw = (r.json().get("message") or {}).get("content") or "{}"
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            last_err = e
            continue
    raise last_err or ValueError("Ollama returned no parseable JSON")


def chat_json(system: str, user: str, max_tokens: int = 800) -> Any:
    if backend.is_ollama():
        return _chat_ollama_native(system, user, max_tokens)
    return _chat_openai_compat(backend.chat_provider(), system, user, max_tokens)


MODEL = backend.PROVIDERS["openai"].chat_model
