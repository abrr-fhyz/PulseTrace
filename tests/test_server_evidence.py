from __future__ import annotations
from unittest.mock import patch
import server as srv
from lib.store import write_json


def _client():
    srv.app.config["TESTING"] = True
    return srv.app.test_client()


def test_run_passes_opinion_to_agent(monkeypatch):
    seen = {}

    def fake_run(topic, sources, run_id=None, opinion=None):
        seen["opinion"] = opinion
        return run_id or "rid"

    monkeypatch.setattr(srv, "run_agent", fake_run)
    def _fake_thread(target, daemon=None):
        class _T:
            def start(self):
                target()
        return _T()

    monkeypatch.setattr(srv.threading, "Thread", _fake_thread)
    c = _client()
    r = c.post("/run", json={"topic": "Elden Ring", "sources": ["reddit"],
                             "opinion": "I want to play it"})
    assert r.status_code == 200
    assert seen["opinion"] == "I want to play it"


def test_evidence_endpoint_serves_json(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.store.ROOT", tmp_path / "runs")
    write_json("rid", "evidence.json", {"opinion": None, "claims": []})
    c = _client()
    r = c.get("/run/rid/evidence")
    assert r.status_code == 200
    assert r.get_json()["claims"] == []


def test_evidence_endpoint_404_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.store.ROOT", tmp_path / "runs")
    c = _client()
    r = c.get("/run/none/evidence")
    assert r.status_code == 404
