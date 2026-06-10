from __future__ import annotations
from unittest.mock import MagicMock
from contextlib import contextmanager
from db.supabase_client import SupabaseClient


def _capture():
    c = SupabaseClient.__new__(SupabaseClient)
    c.enabled = True
    cap = {}
    cur = MagicMock()

    def _ex(sql, params=None):
        cap["sql"] = sql
        cap["params"] = params
    cur.execute.side_effect = _ex
    cur.fetchall.return_value = []

    @contextmanager
    def _conn():
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        yield conn
    c._conn = _conn
    return c, cap


def test_list_conversations_filters_owner():
    c, cap = _capture()
    c.list_conversations("topic-x", owner_email="me@x.com")
    assert "owner_email = %s" in cap["sql"]
    assert "me@x.com" in cap["params"] and "topic-x" in cap["params"]


def test_list_conversations_no_owner():
    c, cap = _capture()
    c.list_conversations("topic-x", owner_email=None)
    assert "owner_email = %s" not in cap["sql"]
    assert "topic-x" in cap["params"]
