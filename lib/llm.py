"""Thin OpenAI chat wrapper with strict JSON parsing + one retry."""
from __future__ import annotations
import json
import os
from typing import Any

from openai import OpenAI


MODEL = os.environ.get("PULSETRACE_LLM_MODEL", "gpt-4o-mini")


def chat_json(system: str, user: str, max_tokens: int = 800) -> Any:
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
