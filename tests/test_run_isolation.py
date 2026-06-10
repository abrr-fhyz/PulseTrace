from __future__ import annotations
import importlib


def test_set_get_run_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("PULSETRACE_DATA_ROOT", str(tmp_path))
    import lib.store as store
    importlib.reload(store)
    store.set_run_owner("run1", "owner@x.com")
    assert store.get_run_owner("run1") == "owner@x.com"
    assert store.get_run_owner("missing") is None


from unittest.mock import MagicMock
from contextlib import contextmanager
from db.supabase_client import SupabaseClient


def _client_with_capture():
    c = SupabaseClient.__new__(SupabaseClient)
    c.enabled = True
    captured = {}
    cur = MagicMock()

    def _execute(sql, params=None):
        captured["sql"] = sql
        captured["params"] = params
    cur.execute.side_effect = _execute
    cur.fetchall.return_value = []

    @contextmanager
    def _conn():
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        yield conn
    c._conn = _conn
    return c, captured


def test_list_runs_filters_by_owner():
    c, captured = _client_with_capture()
    c.list_runs(owner_email="me@x.com", limit=10)
    assert "owner_email = %s" in captured["sql"]
    assert "me@x.com" in captured["params"]


def test_list_runs_no_owner_no_filter():
    c, captured = _client_with_capture()
    c.list_runs(owner_email=None, limit=10)
    assert "owner_email = %s" not in captured["sql"]
