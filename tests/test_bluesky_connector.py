from unittest.mock import patch, MagicMock
import lib.connectors.bluesky as bsky
from lib.connectors.bluesky import BlueskyConnector


def _resp(payload):
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status = lambda: None
    return r


def setup_function():
    bsky._cached_token = None
    bsky._token_at = 0.0


def test_bluesky_no_creds_returns_empty(monkeypatch):
    monkeypatch.delenv("BLUESKY_APP_USERNAME", raising=False)
    monkeypatch.delenv("BSKY_HANDLE", raising=False)
    monkeypatch.delenv("BLUESKY_APP_PASSWORD", raising=False)
    monkeypatch.delenv("BSKY_APP_PASSWORD", raising=False)
    assert BlueskyConnector().fetch("x") == []


def test_bluesky_parses_posts(monkeypatch):
    monkeypatch.setenv("BLUESKY_APP_USERNAME", "me.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "aaaa-bbbb-cccc-dddd")
    search = _resp({"posts": [{
        "uri": "at://did:plc:xyz/app.bsky.feed.post/abc123",
        "record": {"text": "hello world", "createdAt": "2026-06-01T00:00:00Z"},
        "author": {"handle": "me.bsky.social"},
        "likeCount": 5, "replyCount": 2, "repostCount": 1,
        "indexedAt": "2026-06-01T00:00:00Z",
    }]})
    with patch("lib.connectors.bluesky.requests.post",
               return_value=_resp({"accessJwt": "tok"})), \
         patch("lib.connectors.bluesky.requests.get", return_value=search):
        posts = BlueskyConnector().fetch("hello", limit=5)
    assert len(posts) == 1
    p = posts[0]
    assert p.source == "bluesky" and p.reactions == 5 and p.shares == 1
    assert p.author == "me.bsky.social"
    assert p.url == "https://bsky.app/profile/me.bsky.social/post/abc123"


def test_bluesky_session_failure_returns_empty(monkeypatch):
    monkeypatch.setenv("BLUESKY_APP_USERNAME", "me.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "pw")
    with patch("lib.connectors.bluesky.requests.post",
               return_value=_resp({})):  # no accessJwt
        assert BlueskyConnector().fetch("x") == []
