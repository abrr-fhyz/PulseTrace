"""LLM + embedding backend selector.

PULSETRACE_BACKEND ∈ {openai, ollama, gemini, openrouter, groq, pollen, llm7, huggingface}
PULSETRACE_EMBED_BACKEND overrides backend for embeddings (defaults to chat backend,
falling back to openai if chosen provider lacks embedding support).
"""
from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str | None       # None = official openai endpoint
    key_env: str
    chat_model: str
    embed_model: str | None
    embed_dim: int              # 0 = probe at runtime
    extra_headers: dict[str, str] | None = None


_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

PROVIDERS: dict[str, Provider] = {
    "openai": Provider(
        name="openai",
        base_url=None,
        key_env="OPENAI_API_KEY",
        chat_model=os.environ.get("PULSETRACE_LLM_MODEL", "gpt-4o-mini"),
        embed_model="text-embedding-3-small",
        embed_dim=1536,
    ),
    "ollama": Provider(
        name="ollama",
        base_url=f"{_OLLAMA_HOST}/v1",
        key_env="OLLAMA_API_KEY",
        chat_model=os.environ.get("OLLAMA_CHAT_MODEL", "llama3.2:3b"),
        embed_model=os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
        embed_dim=0,
    ),
    "gemini": Provider(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        key_env="GEMINI_API_KEY",
        chat_model=os.environ.get("GEMINI_CHAT_MODEL", "gemini-1.5-flash"),
        embed_model=os.environ.get("GEMINI_EMBED_MODEL", "gemini-embedding-001"),
        embed_dim=768,
    ),
    "openrouter": Provider(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        key_env="OPENROUTER_API_KEY",
        chat_model=os.environ.get("OPENROUTER_CHAT_MODEL", "openai/gpt-4o-mini"),
        embed_model=None,
        embed_dim=0,
        extra_headers={"HTTP-Referer": "https://github.com/pulsetrace", "X-Title": "PulseTrace"},
    ),
    "groq": Provider(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        key_env="GROQ_API_KEY",
        chat_model=os.environ.get("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile"),
        embed_model=None,
        embed_dim=0,
    ),
    "pollen": Provider(
        name="pollen",
        base_url="https://text.pollinations.ai/openai",
        key_env="POLLEN_API_KEY",
        chat_model=os.environ.get("POLLEN_CHAT_MODEL", "openai"),
        embed_model=None,
        embed_dim=0,
    ),
    "llm7": Provider(
        name="llm7",
        base_url="https://api.llm7.io/v1",
        key_env="LLM7_API_KEY",
        chat_model=os.environ.get("LLM7_CHAT_MODEL", "gpt-4o-mini-2024-07-18"),
        embed_model=None,
        embed_dim=0,
    ),
    "huggingface": Provider(
        name="huggingface",
        base_url="https://router.huggingface.co/v1",
        key_env="HUGGINGFACE_TOKEN",
        chat_model=os.environ.get("HF_CHAT_MODEL", "meta-llama/Llama-3.3-70B-Instruct"),
        embed_model=None,
        embed_dim=0,
    ),
}


def name() -> str:
    return (os.environ.get("PULSETRACE_BACKEND", "openai") or "openai").lower().strip()


def is_ollama() -> bool:
    return name() == "ollama"


def is_openai() -> bool:
    return name() == "openai"


def chat_provider() -> Provider:
    n = name()
    if n not in PROVIDERS:
        raise ValueError(f"unknown PULSETRACE_BACKEND={n!r}; choose {sorted(PROVIDERS)}")
    return PROVIDERS[n]


def embed_provider() -> Provider:
    """Provider for embeddings. Falls back to openai if chat provider has none."""
    override = (os.environ.get("PULSETRACE_EMBED_BACKEND") or "").lower().strip()
    candidate = PROVIDERS.get(override) if override else chat_provider()
    if candidate and candidate.embed_model:
        return candidate
    return PROVIDERS["openai"]


# Back-compat constants (still used by lib.llm / lib.embed for native ollama path).
OLLAMA_HOST = _OLLAMA_HOST
OLLAMA_CHAT_MODEL = PROVIDERS["ollama"].chat_model
OLLAMA_EMBED_MODEL = PROVIDERS["ollama"].embed_model or "nomic-embed-text"
OLLAMA_CHAT_TIMEOUT = int(os.environ.get("OLLAMA_CHAT_TIMEOUT", "600"))
OLLAMA_EMBED_TIMEOUT = int(os.environ.get("OLLAMA_EMBED_TIMEOUT", "300"))
