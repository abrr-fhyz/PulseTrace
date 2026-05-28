import os
import pytest
from lib.connectors.base import Post


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
