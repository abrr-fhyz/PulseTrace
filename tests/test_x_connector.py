from lib.connectors.x import XConnector


def test_fetch_no_creds_returns_empty(monkeypatch, tmp_path):
    from lib.connectors import x as xmod
    monkeypatch.setattr(xmod, "COOKIE_PATH", tmp_path / "none.json")
    monkeypatch.delenv("X_USERNAME", raising=False)
    monkeypatch.delenv("X_PASSWORD", raising=False)
    assert XConnector().fetch("anything") == []
