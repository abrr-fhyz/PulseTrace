"""Shared fixtures for staged pipeline tests.

Each `test_NN_*.py` exercises one stage of the agent in isolation so that
failures localize to the smallest broken unit.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT / ".env.example", override=False)

from lib.keys import load as _load_api_keys  # noqa: E402

_load_api_keys(REPO_ROOT / ".env.api_keys")


TOPIC = os.environ.get("PT_TEST_TOPIC", "Donald Trump Buffalo")
CHAT_PROVIDERS = ["gemini", "groq", "openrouter", "llm7", "huggingface", "pollen"]
EMBED_PROVIDERS = ["gemini", "ollama"]
RESULTS_DIR = REPO_ROOT / "results"

# Configurable RAG questions for stage 14. Override with PT_RAG_QUESTIONS as
# pipe-separated string, e.g. "what is X?|who is most critical?".
_DEFAULT_RAG_QS = (
    "What are the main themes in this conversation?"
    "|What are the biggest complaints?"
    "|Who or what is mentioned most often?"
    "|Is sentiment more positive or negative overall?"
)
RAG_QUESTIONS = [q.strip() for q in os.environ.get(
    "PT_RAG_QUESTIONS", _DEFAULT_RAG_QS).split("|") if q.strip()]


def pick_chat_provider() -> str | None:
    from lib import backend
    for prov in CHAT_PROVIDERS:
        p = backend.PROVIDERS.get(prov)
        if p and os.environ.get(p.key_env):
            return prov
    return None


def pick_embed_provider() -> str | None:
    """Prefer local Ollama (free + already proven), else Gemini."""
    import requests
    try:
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        if requests.get(f"{host}/api/tags", timeout=3).status_code == 200:
            return "ollama"
    except Exception:
        pass
    if has_key("gemini"):
        return "gemini"
    return None


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def topic() -> str:
    return TOPIC


@pytest.fixture(scope="session")
def shared_state() -> dict:
    """Tiny cross-stage cache so later stages can reuse picks from earlier ones."""
    return {}


def has_key(provider: str) -> bool:
    from lib import backend
    p = backend.PROVIDERS.get(provider)
    return bool(p and os.environ.get(p.key_env))


def write_stage_artifact(name: str, payload: dict) -> Path:
    out = REPO_ROOT / "test_artifacts"
    out.mkdir(exist_ok=True)
    p = out / name
    p.write_text(json.dumps(payload, indent=2, default=str))
    return p
