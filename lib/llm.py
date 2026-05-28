"""Strict-JSON chat wrapper with one retry. Dispatches openai or ollama."""
from __future__ import annotations
import json
import os
from typing import Any

import requests
from openai import OpenAI

from . import backend


MODEL = os.environ.get("PULSETRACE_LLM_MODEL", "gpt-4o-mini")


def _chat_openai(system: str, user: str, max_tokens: int) -> Any:
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    last_err: Exception | None = None
    for _ in range(2):
        resp = client.chat.completions.create(
            model=MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        raw = resp.choices[0].message.content or "{}"
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            last_err = e
            continue
    raise last_err or ValueError("LLM returned no parseable JSON")


def _chat_ollama(system: str, user: str, max_tokens: int) -> Any:
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
    last_err: Exception | None = None
    for _ in range(2):
        try:
            r = requests.post(url, json=payload, timeout=backend.OLLAMA_CHAT_TIMEOUT)
            r.raise_for_status()
        except Exception as e:
            last_err = e
            continue
        data = r.json()
        raw = (data.get("message") or {}).get("content") or "{}"
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            last_err = e
            continue
    raise last_err or ValueError("Ollama returned no parseable JSON")


def chat_json(system: str, user: str, max_tokens: int = 800) -> Any:
    if backend.is_ollama():
        return _chat_ollama(system, user, max_tokens)
    return _chat_openai(system, user, max_tokens)
