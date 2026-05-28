from lib.connectors.facebook import _parse_engagement, FacebookConnector


def test_parse_engagement_basic():
    txt = "Cool post here\n1.2K\n345 comments"
    r, c = _parse_engagement(txt)
    assert c == 345
    assert r == 1200


def test_parse_engagement_none():
    assert _parse_engagement("no numbers here") == (0, 0)


def test_fetch_missing_cookies_returns_empty(tmp_path, monkeypatch):
    from lib.connectors import facebook as fb
    monkeypatch.setattr(fb, "COOKIE_PATH", tmp_path / "nope.json")
    assert FacebookConnector().fetch("test") == []
