"""Stage 4: HN connector returns Posts for the test topic."""
from __future__ import annotations

import pytest

from .conftest import TOPIC, write_stage_artifact


def test_hn_returns_posts_for_topic():
    """Soft check — zero posts means the topic itself has no HN coverage,
    not that the connector is broken. `test_hn_query_variants` is the
    hard pipeline check."""
    from lib.connectors.hn import HNConnector
    posts = HNConnector().fetch(TOPIC, limit=20)
    write_stage_artifact("stage04_hn.json", {
        "topic": TOPIC,
        "n": len(posts),
        "sample": [{"id": p.id, "text": p.text[:200]} for p in posts[:3]],
    })
    assert isinstance(posts, list)
    if len(posts) == 0:
        pytest.skip(f"HN has no coverage for topic {TOPIC!r} "
                    f"(connector works — see test_hn_query_variants)")
    p0 = posts[0]
    assert p0.id.startswith("hn:")
    assert p0.source == "hn"
    assert p0.text


def test_hn_query_variants():
    """At least one of these queries must yield results — sanity for live API."""
    from lib.connectors.hn import HNConnector
    c = HNConnector()
    hits = {q: len(c.fetch(q, limit=5))
            for q in [TOPIC, "Donald Trump", "election", "Buffalo"]}
    write_stage_artifact("stage04_hn_variants.json", hits)
    assert max(hits.values()) > 0
