"""Stage 5: Facebook connector.

Skips cleanly when `info/cookies.json` is absent (the only supported v2 auth
path) — burner email/password in `.env.example` is not enough; v2 reads
cookies, not creds.
"""
from __future__ import annotations
import os
from pathlib import Path

import pytest

from .conftest import TOPIC, REPO_ROOT, write_stage_artifact


COOKIES = REPO_ROOT / "info" / "cookies.json"


def test_fb_connector_imports_without_cookies():
    """Connector class must construct and short-circuit to [] when no cookies."""
    from lib.connectors.facebook import FacebookConnector
    conn = FacebookConnector(headless=True, scrolls=0)
    if COOKIES.exists():
        pytest.skip("cookies present -> covered by live test below")
    posts = conn.fetch(TOPIC, limit=2)
    write_stage_artifact("stage05_fb_no_cookies.json",
                         {"posts": len(posts), "cookies_path": str(COOKIES)})
    assert posts == []


@pytest.mark.skipif(not COOKIES.exists() or os.environ.get("FB_INTEGRATION") != "1",
                    reason="set FB_INTEGRATION=1 and place info/cookies.json to run live")
def test_fb_live_fetch_returns_posts():
    from lib.connectors.facebook import FacebookConnector
    posts = FacebookConnector(headless=True, scrolls=2).fetch(TOPIC, limit=5)
    write_stage_artifact("stage05_fb_live.json", {
        "topic": TOPIC,
        "n": len(posts),
        "sample": [{"id": p.id, "text": p.text[:200]} for p in posts[:2]],
    })
    assert len(posts) >= 1
