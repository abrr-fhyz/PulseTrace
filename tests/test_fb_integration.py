"""Live Facebook connector integration test.

Requires:
  FB_INTEGRATION=1
  info/cookies.json populated from a logged-in browser session.
  Playwright Chromium installed: .venv/bin/python -m playwright install chromium

Run with:
  FB_INTEGRATION=1 .venv/bin/python -m pytest tests/test_fb_integration.py -v -m slow

Override headless / scroll count via env:
  FB_HEADLESS=0          (default 1; set 0 to see the browser)
  FB_TEST_QUERY="ai"     (default "technology")
  FB_TEST_SCROLLS=3      (default 3)
"""
from __future__ import annotations
import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.slow


def _enabled() -> bool:
    return os.environ.get("FB_INTEGRATION", "") == "1"


def _cookies_present() -> bool:
    p = Path("info/cookies.json")
    return p.exists() and p.stat().st_size > 50


_GATE = pytest.mark.skipif(
    not _enabled(), reason="set FB_INTEGRATION=1 to run"
)
_COOKIES = pytest.mark.skipif(
    not _cookies_present(), reason="info/cookies.json missing or empty"
)


@_GATE
@_COOKIES
def test_facebook_connector_returns_posts():
    from lib.connectors.facebook import FacebookConnector
    headless = os.environ.get("FB_HEADLESS", "1") != "0"
    scrolls = int(os.environ.get("FB_TEST_SCROLLS", "3"))
    query = os.environ.get("FB_TEST_QUERY", "technology")

    posts = FacebookConnector(headless=headless, scrolls=scrolls).fetch(query, limit=10)
    assert isinstance(posts, list)
    assert len(posts) > 0, "FB returned 0 posts — cookies stale or selectors drifted"
    for p in posts:
        assert p.source == "facebook"
        assert p.id.startswith("facebook:")
        assert isinstance(p.text, str) and len(p.text) > 0
        assert p.reactions >= 0 and p.comments >= 0


@_GATE
@_COOKIES
def test_facebook_post_text_is_meaningful():
    from lib.connectors.facebook import FacebookConnector
    headless = os.environ.get("FB_HEADLESS", "1") != "0"
    posts = FacebookConnector(headless=headless, scrolls=2).fetch(
        os.environ.get("FB_TEST_QUERY", "technology"), limit=5,
    )
    if not posts:
        pytest.skip("no posts; covered by previous test")
    longest = max(len(p.text) for p in posts)
    assert longest > 50, "all posts shorter than 50 chars — extraction degraded"
