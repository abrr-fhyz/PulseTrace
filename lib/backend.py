"""LLM + embedding backend selector.

PULSETRACE_BACKEND=openai|ollama  (default: openai)
"""
from __future__ import annotations
import os


def name() -> str:
    return os.environ.get("PULSETRACE_BACKEND", "openai").lower().strip() or "openai"


def is_ollama() -> bool:
    return name() == "ollama"


def is_openai() -> bool:
    return name() == "openai"


OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "llama3.2:3b")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")

OLLAMA_CHAT_TIMEOUT = int(os.environ.get("OLLAMA_CHAT_TIMEOUT", "600"))
OLLAMA_EMBED_TIMEOUT = int(os.environ.get("OLLAMA_EMBED_TIMEOUT", "300"))
