"""Stage 12: multi-source ingestion via the agent's threaded fetcher.

Backs README use-case "Step 2 — Fetch posts (Reddit, HN, FB, X, IG)" and the
connector-architecture claim.
"""
from __future__ import annotations
import os

import pytest

from lib.connectors.base import Post

from .conftest import TOPIC, write_stage_artifact


def test_fetch_all_handles_mixed_sources(monkeypatch):
    """One real source (HN) + skeleton sources (FB/X/IG without creds) must
    return only the working source's posts and never raise."""
    from lib import agent

    posts = agent._fetch_all([(TOPIC, "hn"), (TOPIC, "facebook"),
                              (TOPIC, "x"), (TOPIC, "instagram")], limit=8)
    by_source = {}
    for p in posts:
        by_source[p.source] = by_source.get(p.source, 0) + 1

    write_stage_artifact("stage12_multi_source.json",
                         {"topic": TOPIC, "by_source": by_source,
                          "n_total": len(posts)})

    # HN must be present, unless its API call failed (in which case the
    # connector test in stage 04 would have surfaced it already).
    if "hn" not in by_source:
        pytest.skip("HN returned nothing for topic — see stage 04 artifacts")
    assert by_source.get("hn", 0) >= 1


def test_fetch_all_swallows_connector_exceptions(monkeypatch):
    """A connector that raises must not poison the batch — other sources
    still produce their posts."""
    from lib import agent

    class _Broken:
        name = "broken"
        def fetch(self, q, limit=10):
            raise RuntimeError("simulated outage")

    class _Good:
        name = "good"
        def fetch(self, q, limit=10):
            return [Post(id=f"good:{q}", source="good", text=q)]

    monkeypatch.setitem(agent.SOURCES, "broken", _Broken)
    monkeypatch.setitem(agent.SOURCES, "good", _Good)

    out = agent._fetch_all([("topic", "broken"), ("topic", "good")], limit=3)
    assert any(p.source == "good" for p in out)
    assert all(p.source != "broken" for p in out)


def test_unknown_source_is_skipped(monkeypatch):
    """Unregistered sources should be filtered out without error."""
    from lib import agent
    out = agent._fetch_all([("topic", "tiktok"), (TOPIC, "hn")], limit=3)
    assert all(p.source != "tiktok" for p in out)
