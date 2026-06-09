"""Live conversation/message persistence — gated on DATABASE_URL.

Skipped in the default (mocked) suite; runs against a real Supabase/Postgres
when DATABASE_URL is set and the schema has been applied.
"""
from __future__ import annotations

import os
import uuid

import pytest

from db.supabase_client import SupabaseClient

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")),
    reason="no DATABASE_URL — live DB test",
)


@pytest.fixture()
def pg():
    client = SupabaseClient()
    assert client.enabled, "expected an enabled client with DATABASE_URL set"
    client.apply_schema("db/schema.sql")
    yield client
    client.close()


def test_conversation_roundtrip(pg):
    cid = "test_" + uuid.uuid4().hex[:8]
    try:
        conv = {"id": cid, "topic_id": "t-pytest", "run_id": "r-pytest",
                "title": "First Q", "summary": "", "archived_count": 0}
        assert pg.upsert_conversation(conv) is True

        assert pg.insert_message(cid, "user", "hello", {"confidence": None}) is True
        assert pg.insert_message(cid, "assistant", "hi there", {"confidence": 0.9}) is True

        msgs = pg.get_messages(cid)
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert msgs[1]["content"] == "hi there"
        assert msgs[1]["metadata"]["confidence"] == 0.9

        got = pg.get_conversation(cid)
        assert got["title"] == "First Q"

        rows = pg.list_conversations("t-pytest")
        assert any(r["id"] == cid and r["message_count"] == 2 for r in rows)

        assert pg.delete_conversation(cid) is True
        assert pg.get_conversation(cid) is None
        assert pg.get_messages(cid) == []  # FK cascade
    finally:
        pg.delete_conversation(cid)


def test_upsert_updates_existing(pg):
    cid = "test_" + uuid.uuid4().hex[:8]
    base = {"id": cid, "topic_id": "t-pytest", "run_id": "r-pytest",
            "title": "v1", "summary": "", "archived_count": 0}
    try:
        assert pg.upsert_conversation(base) is True
        first = pg.get_conversation(cid)
        base2 = {**base, "title": "v2", "summary": "rolled up", "archived_count": 3}
        assert pg.upsert_conversation(base2) is True
        got = pg.get_conversation(cid)
        assert got["title"] == "v2"
        assert got["summary"] == "rolled up"
        assert got["archived_count"] == 3
        # only one row (update, not insert)
        rows = [r for r in pg.list_conversations("t-pytest") if r["id"] == cid]
        assert len(rows) == 1
    finally:
        pg.delete_conversation(cid)
