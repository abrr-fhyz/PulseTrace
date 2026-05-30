"""Strict-JSON chat wrapper.

Prod path: `chat_json()` calls `backend.chat_provider()` directly — single
provider (Gemini by default), no cascade. The `stage=` parameter is accepted
for back-compat with old call sites but ignored.

Test/legacy path: `chat_json_cascade()` walks `lib.dispatch.cascade_for_stage()`,
trying each credentialed provider with retryable-error fallthrough. Used by
`tests/stages/test_16_cascade.py` to exercise the cascade dispatcher; not
imported by any prod stage.
"""
from __future__ import annotations
import json
import os
from typing import Any

import requests
from openai import OpenAI

from . import backend, dispatch


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
                return _coerce_dict(json.loads(_strip_fence(raw)))
            except json.JSONDecodeError as e:
                last_err = e
                continue
            except Exception as e:
                last_err = e
                break
    raise last_err or ValueError(f"{p.name}: no parseable JSON")


def _coerce_dict(payload: Any) -> dict:
    """Some Gemini variants return a top-level array even under json_object
    mode. Normalise so every caller gets a dict it can .get() on.
    Single-dict array -> that dict. Anything else -> {"items": payload}."""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        if len(payload) == 1 and isinstance(payload[0], dict):
            return payload[0]
        return {"items": payload}
    return {"value": payload}


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
            return _coerce_dict(json.loads(raw))
        except json.JSONDecodeError as e:
            last_err = e
            continue
    raise last_err or ValueError("Ollama returned no parseable JSON")


def _dispatch_one(p: backend.Provider, system: str, user: str, max_tokens: int) -> Any:
    if p.name == "ollama":
        return _chat_ollama_native(system, user, max_tokens)
    return _chat_openai_compat(p, system, user, max_tokens)


def chat_json(system: str, user: str, max_tokens: int = 800, *, stage: str = "default") -> Any:
    p = backend.chat_provider()
    debug = os.environ.get("PT_LLM_DEBUG") == "1"
    if debug:
        print(f"[llm] stage={stage} direct -> {p.name}:{p.chat_model}", flush=True)
    return _dispatch_one(p, system, user, max_tokens)


def chat_json_cascade(system: str, user: str, max_tokens: int = 800,
                      *, stage: str = "default") -> Any:
    chain = dispatch.cascade_for_stage(stage)
    debug = os.environ.get("PT_LLM_DEBUG") == "1"
    if debug:
        print(f"[llm] cascade stage={stage} chain={[p.name for p in chain]}", flush=True)
    last_err: Exception | None = None
    for p in chain:
        try:
            r = _dispatch_one(p, system, user, max_tokens)
            if debug:
                print(f"[llm] cascade stage={stage} OK via {p.name}", flush=True)
            return r
        except Exception as e:
            last_err = e
            if debug:
                print(f"[llm] cascade stage={stage} {p.name} FAIL: "
                      f"{type(e).__name__}: {str(e)[:140]}", flush=True)
            if dispatch.is_retryable(e):
                continue
            raise
    raise last_err or RuntimeError("cascade exhausted with no providers")


MODEL = backend.PROVIDERS["gemini"].chat_model
