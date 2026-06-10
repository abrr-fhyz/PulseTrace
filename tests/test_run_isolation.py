from __future__ import annotations
import importlib


def test_set_get_run_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("PULSETRACE_DATA_ROOT", str(tmp_path))
    import lib.store as store
    importlib.reload(store)
    store.set_run_owner("run1", "owner@x.com")
    assert store.get_run_owner("run1") == "owner@x.com"
    assert store.get_run_owner("missing") is None
