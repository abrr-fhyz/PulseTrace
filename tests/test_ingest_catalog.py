from __future__ import annotations

from lib.ingest.catalog import (
    Catalog,
    normalize_author,
    normalize_text,
    normalize_url,
    stable_id,
)


def _p(**over):
    base = {"id": "a", "source": "reddit", "text": "Hello World"}
    base.update(over)
    return base


def test_normalize_text_collapses_and_strips():
    assert normalize_text("  too   many\n spaces ") == "too many spaces"


def test_normalize_author_strips_prefixes_and_lowercases():
    assert normalize_author("/u/SomeUser") == "someuser"
    assert normalize_author("@Handle") == "handle"
    assert normalize_author(None) == ""


def test_normalize_url_drops_tracking_and_trailing_slash():
    url = "HTTPS://Reddit.com/r/x/comments/1/?utm_source=foo&ref=bar"
    assert normalize_url(url) == "https://reddit.com/r/x/comments/1"


def test_normalize_url_keeps_meaningful_query():
    url = "https://example.com/search?q=cats"
    assert normalize_url(url) == "https://example.com/search?q=cats"


def test_normalize_url_empty():
    assert normalize_url("") == ""
    assert normalize_url(None) == ""


def test_stable_id_is_deterministic():
    assert stable_id("reddit", "Hello World") == stable_id("reddit", "Hello World")


def test_stable_id_ignores_surrounding_whitespace_and_case():
    assert stable_id("reddit", "Hello World") == stable_id("reddit", "  hello   world ")


def test_stable_id_differs_by_source_and_content():
    assert stable_id("reddit", "x") != stable_id("hn", "x")
    assert stable_id("reddit", "x") != stable_id("reddit", "y")


def test_catalog_add_returns_stable_id_and_get_roundtrips():
    cat = Catalog()
    cid = cat.add(_p())
    assert cid == stable_id("reddit", "Hello World")
    entry = cat.get(cid)
    assert entry["catalog_id"] == cid
    assert entry["source"] == "reddit"


def test_catalog_normalizes_author_and_url_on_entry():
    cat = Catalog()
    cid = cat.add(_p(author="/u/Bob", url="https://x.com/a/?utm_source=z"))
    entry = cat.get(cid)
    assert entry["author"] == "bob"
    assert entry["url"] == "https://x.com/a"


def test_catalog_dedupes_same_content_keep_first():
    cat = Catalog()
    cat.add(_p(id="first", text="same body"))
    cat.add(_p(id="second", text="  SAME   body "))
    assert len(cat) == 1
    only = cat.all()[0]
    assert only["id"] == "first"


def test_catalog_contains_and_missing_lookup():
    cat = Catalog()
    cid = cat.add(_p())
    assert cid in cat
    assert cat.get("cat:does-not-exist") is None


def test_catalog_by_source():
    cat = Catalog()
    cat.add(_p(id="r1", source="reddit", text="one"))
    cat.add(_p(id="h1", source="hn", text="two"))
    cat.add(_p(id="r2", source="reddit", text="three"))
    assert {e["id"] for e in cat.by_source("reddit")} == {"r1", "r2"}
    assert len(cat.by_source("hn")) == 1
