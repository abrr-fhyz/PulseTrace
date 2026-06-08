import os
import pytest
from unittest.mock import patch, MagicMock
from lib.connectors.base import Post


_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <author><name>/u/alice</name></author>
    <category term="r/test" />
    <title>Great topic discussion</title>
    <link href="https://www.reddit.com/r/test/comments/abc123/great_topic/" />
    <updated>2026-06-01T00:00:00+00:00</updated>
    <content type="html">&lt;p&gt;Body text here&lt;/p&gt;</content>
  </entry>
</feed>"""


def test_reddit_rss_fallback_when_no_creds(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    from lib.connectors.reddit import RedditConnector
    r = MagicMock()
    r.text = _RSS
    r.raise_for_status = lambda: None
    with patch("lib.connectors.reddit.requests.get", return_value=r):
        posts = RedditConnector().fetch("topic", limit=5)
    assert len(posts) == 1
    p = posts[0]
    assert p.source == "reddit" and p.author == "alice"
    assert "Great topic discussion" in p.text and "Body text" in p.text
    assert p.raw["via"] == "rss" and p.raw["subreddit"] == "test"


def test_reddit_rss_network_error_returns_empty(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    import requests
    from lib.connectors.reddit import RedditConnector
    with patch("lib.connectors.reddit.requests.get",
               side_effect=requests.RequestException("boom")):
        assert RedditConnector().fetch("x") == []


def test_post_dataclass_roundtrip():
    p = Post(id="x:1", source="x", text="hi", ts=1)
    d = p.to_dict()
    assert d["id"] == "x:1" and d["source"] == "x" and d["text"] == "hi"


@pytest.mark.skipif(
    not os.environ.get("REDDIT_CLIENT_ID"),
    reason="needs REDDIT_CLIENT_ID env",
)
def test_reddit_fetch_smoke():
    from lib.connectors.reddit import RedditConnector
    posts = RedditConnector().fetch("openai", limit=3)
    assert len(posts) > 0
    assert all(p.source == "reddit" and p.text for p in posts)
