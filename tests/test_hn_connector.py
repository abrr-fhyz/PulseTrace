from unittest.mock import patch, MagicMock
from lib.connectors.hn import HNConnector


def test_hn_parses_hits():
    fake = {"hits": [
        {"objectID": "1", "title": "Hello", "story_text": "world",
         "author": "a", "url": "https://e.com", "created_at_i": 100,
         "points": 5, "num_comments": 2},
    ]}
    resp = MagicMock(status_code=200)
    resp.json.return_value = fake
    resp.raise_for_status = lambda: None
    with patch("lib.connectors.hn.requests.get", return_value=resp):
        posts = HNConnector().fetch("hi", limit=1)
    assert len(posts) == 1
    p = posts[0]
    assert p.source == "hn" and p.reactions == 5 and "Hello" in p.text
    assert p.url == "https://e.com"


def test_hn_skips_empty():
    fake = {"hits": [{"objectID": "2", "title": None, "story_text": None}]}
    resp = MagicMock()
    resp.json.return_value = fake
    resp.raise_for_status = lambda: None
    with patch("lib.connectors.hn.requests.get", return_value=resp):
        assert HNConnector().fetch("x") == []
