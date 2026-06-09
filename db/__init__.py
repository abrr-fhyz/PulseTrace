"""Tiered storage layer — injectable Postgres/pgvector + Mongo clients.

Both clients are *additive*: they activate only when their connection env vars
are present (`DATABASE_URL`/`SUPABASE_DB_URL`, `MONGODB_URI`). When absent the
factories return a disabled instance whose `.enabled is False`, and callers
keep using the file-based `lib/store.py` + FAISS path. This lets the same code
run a cold demo and a fully-provisioned deployment unchanged.

Inject into the MCP server / agent like:

    from db import get_supabase, get_mongo
    pg, mongo = get_supabase(), get_mongo()
    if pg.enabled:
        pg.insert_posts(records)
"""
from __future__ import annotations

try:  # make the clients work purely from .env regardless of caller
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv optional
    pass

from .models import PostRecord, RunRecord
from .mongo_client import MongoClient
from .supabase_client import SupabaseClient

__all__ = [
    "SupabaseClient",
    "MongoClient",
    "PostRecord",
    "RunRecord",
    "get_supabase",
    "get_mongo",
]

_supabase: SupabaseClient | None = None
_mongo: MongoClient | None = None


def get_supabase() -> SupabaseClient:
    """Process-wide singleton — one connection pool, reused everywhere."""
    global _supabase
    if _supabase is None:
        _supabase = SupabaseClient()
    return _supabase


def get_mongo() -> MongoClient:
    """Process-wide singleton — one pooled Mongo client, reused everywhere."""
    global _mongo
    if _mongo is None:
        _mongo = MongoClient()
    return _mongo
