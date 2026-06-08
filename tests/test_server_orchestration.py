from __future__ import annotations

import server as srv


def _client():
    srv.app.config["TESTING"] = True
    return srv.app.test_client()


def _sync_threads(monkeypatch):
    def _fake_thread(target, daemon=None):
        class _T:
            def start(self):
                target()
        return _T()

    monkeypatch.setattr(srv.threading, "Thread", _fake_thread)


def test_orchestration_requires_topic():
    c = _client()
    r = c.post("/api/agent/run", json={"sources": ["reddit"]})
    assert r.status_code == 400
    assert "topic" in r.get_json()["error"]


def test_orchestration_runs_graph_and_returns_run_id(monkeypatch):
    seen = {}

    def fake_run(topic, sources, run_id):
        seen.update(topic=topic, sources=sources, run_id=run_id)
        return {"n_items": 0}

    monkeypatch.setattr(srv, "run_graph_streamed", fake_run)
    _sync_threads(monkeypatch)

    c = _client()
    r = c.post("/api/agent/run", json={"topic": "electric cars", "sources": ["reddit", "hn"]})
    assert r.status_code == 200
    rid = r.get_json()["run_id"]
    assert seen["topic"] == "electric cars"
    assert seen["sources"] == ["reddit", "hn"]
    assert seen["run_id"] == rid
