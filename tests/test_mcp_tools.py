"""Tests for the real MCP tools. No mock product data — fixtures are real run
files written through lib.store; only external LLM IO is patched."""
from __future__ import annotations
import shutil
from unittest.mock import patch

import pytest

from lib import store
from lib.mcp import data_tools as dt
from lib.mcp import intelligence_tools as it
from lib.mcp.schema import validate_posts


def _post(pid: str, text: str, author: str, reactions: int, comments: int,
          shares: int, ts: int = 1780000000, source: str = "reddit") -> dict:
    return {
        "id": pid, "source": source, "text": text, "author": author,
        "url": f"https://x/{pid}", "ts": ts, "reactions": reactions,
        "comments": comments, "shares": shares, "raw": {"k": "v"},
    }


@pytest.fixture
def run():
    run_id = store.new_run_id()
    posts = [
        _post("reddit:1", "love the new privacy policy", "alice", 50, 5, 2),
        _post("reddit:2", "hate the new privacy policy", "bob", 5, 1, 0),
        _post("reddit:3", "privacy policy is fine i guess", "carol", 200, 40, 10),
    ]
    clusters = [
        {"id": 0, "label": "privacy support", "desc": "", "centroid": [],
         "members": ["reddit:1", "reddit:3"],
         "sentiment": {"pos": 0.5, "neu": 0.5, "neg": 0.0}, "top_posts": []},
        {"id": 1, "label": "privacy backlash", "desc": "", "centroid": [],
         "members": ["reddit:2"],
         "sentiment": {"pos": 0.0, "neu": 0.0, "neg": 1.0}, "top_posts": []},
    ]
    store.write_json(run_id, "posts.json", posts)
    store.write_json(run_id, "clusters.json", clusters)
    store.write_json(run_id, "run.json", {
        "id": run_id, "topic": "privacy policy", "sources": ["reddit"],
        "started_at": 9999999000, "finished_at": 9999999100,
        "queries": [{"q": "privacy", "source": "reddit", "iter": 1}],
        "stop_reason": "converged",
        "metrics": {"posts": 3, "clusters": 2},
    })
    yield run_id
    shutil.rmtree(store.ROOT / run_id, ignore_errors=True)


# --- schema validation (pure) ---

def test_validate_posts_all_good():
    posts = [_post("a", "t", "u", 1, 1, 1)]
    rep = validate_posts(posts)
    assert rep["pass_rate"] == 100.0
    assert rep["failed_records"] == 0
    assert rep["failed_fields"] == {}


def test_validate_posts_catches_missing_and_wrong_type():
    posts = [
        {"id": "a", "source": "reddit", "text": "t", "ts": 1,
         "reactions": "lots", "comments": 0, "shares": 0},  # wrong_type + missing none
        {"source": "reddit", "text": "t", "ts": 1, "reactions": 0,
         "comments": 0, "shares": 0},  # missing id
    ]
    rep = validate_posts(posts)
    assert rep["total_records"] == 2
    assert rep["failed_records"] == 2
    assert rep["failed_fields"]["reactions"] == 1
    assert rep["failed_fields"]["id"] == 1
    assert set(rep["error_types"]) == {"missing", "wrong_type"}


def test_validate_posts_empty_required_string():
    rep = validate_posts([_post("", "t", "u", 1, 1, 1)])
    assert rep["failed_fields"]["id"] == 1
    assert "empty" in rep["error_types"]


# --- Group B: data access ---

def test_get_posts_by_session_returns_engagement(run):
    out = dt.get_posts_by_session(run)
    assert out["count"] == 3
    assert all("engagement_score" in p for p in out["posts"])


def test_get_posts_by_session_keyword_filter(run):
    out = dt.get_posts_by_session(run, keyword="hate")
    assert out["count"] == 1
    assert out["posts"][0]["id"] == "reddit:2"


def test_get_posts_by_session_min_engagement(run):
    high = dt.get_posts_by_session(run, min_engagement=999)
    assert high["count"] == 0


def test_get_posts_unknown_session():
    out = dt.get_posts_by_session("nope")
    assert out["error"] == "no such session"


def test_get_post_detail_with_session(run):
    out = dt.get_post_detail("reddit:2", session_id=run)
    assert out["author"] == "bob"
    assert out["raw"] == {"k": "v"}
    assert "engagement_score" in out


def test_get_post_detail_not_found(run):
    out = dt.get_post_detail("reddit:999", session_id=run)
    assert out["error"] == "no such post in session"


def test_get_top_posts_ranked_by_influence(run):
    out = dt.get_top_posts(run, limit=2)
    assert out["count"] == 2
    # carol has highest reactions/comments/shares
    assert out["posts"][0]["author"] == "carol"


def test_get_keyword_summary(run):
    out = dt.get_keyword_summary(run)
    labels = {k["keyword"] for k in out["keywords"]}
    assert labels == {"privacy support", "privacy backlash"}
    support = next(k for k in out["keywords"] if k["keyword"] == "privacy support")
    assert support["post_volume"] == 2
    assert support["average_engagement"] > 0


# --- Group A: crawl control ---

def test_get_crawl_status_completed(run):
    out = dt.get_crawl_status(run)
    assert out["status"] == "completed"
    assert out["posts_collected"] == 3
    assert out["iterations"] == 1


def test_get_crawl_status_unknown():
    assert dt.get_crawl_status("nope")["status"] == "unknown"


def test_list_crawl_sessions_includes_run(run):
    out = dt.list_crawl_sessions(limit=100)
    ids = {s["session_id"] for s in out["sessions"]}
    assert run in ids


def test_cancel_already_finished(run):
    out = dt.cancel_crawl_session(run)
    assert out["cancelled"] is False
    assert out["status"] == "completed"


def test_cancel_flag_mechanics():
    rid = store.new_run_id()
    store.run_dir(rid)
    try:
        assert store.is_cancelled(rid) is False
        store.request_cancel(rid)
        assert store.is_cancelled(rid) is True
        store.clear_cancel(rid)
        assert store.is_cancelled(rid) is False
    finally:
        shutil.rmtree(store.ROOT / rid, ignore_errors=True)


def test_cancel_running_session_sets_flag():
    rid = store.new_run_id()
    # running = clusters present, run.json not finalized
    store.write_json(rid, "clusters.json", [])
    try:
        out = dt.cancel_crawl_session(rid)
        assert out["cancelled"] is True
        assert store.is_cancelled(rid) is True
    finally:
        shutil.rmtree(store.ROOT / rid, ignore_errors=True)


# --- Group C: inference ---

def test_consensus_narrative_weighted():
    clusters = [
        {"members": ["a", "b", "c"], "sentiment": {"pos": 1, "neu": 0, "neg": 0}},
        {"members": ["d"], "sentiment": {"pos": 0, "neu": 0, "neg": 1}},
    ]
    text = it._consensus_narrative(clusters)
    assert "positive" in text


def test_get_sentiment_breakdown(run):
    out = it.get_sentiment_breakdown(run)
    o = out["overall_sentiment"]
    assert abs(o["pos"] + o["neu"] + o["neg"] - 1.0) < 0.01
    assert out["sample_size"] == 3
    assert 0.0 <= out["confidence"] <= 1.0


def test_run_inference_persists(run):
    with patch("lib.briefing._exec_summary", return_value="A clear summary."):
        out = it.run_inference(run)
    assert out["status"] == "completed"
    assert out["executive_summary"] == "A clear summary."
    assert "carol" in out["top_users"]
    # persisted
    doc = store.read_json(run, "inference.json")
    assert doc["executive_summary"] == "A clear summary."


def test_get_inference_result_builds_when_missing(run):
    with patch("lib.briefing._exec_summary", return_value="Built on demand."):
        out = it.get_inference_result(run)
    assert out["executive_summary"] == "Built on demand."


def test_run_inference_not_ready():
    rid = store.new_run_id()
    store.run_dir(rid)
    try:
        out = it.run_inference(rid)
        assert "error" in out
    finally:
        shutil.rmtree(store.ROOT / rid, ignore_errors=True)


def test_query_rag_unknown_session():
    out = it.query_rag("nope", "what?")
    assert out["citations"] == []


# --- Group D: admin ---

def test_schema_validation_report(run):
    out = it.get_schema_validation_report(run)
    assert out["pass_rate"] == 100.0
    assert out["total_records"] == 3


def test_enrichment_batch_idempotent(run):
    with patch("lib.stance.score_batch", return_value=["pos", "neg", "neu"]):
        first = it.trigger_enrichment_batch(run)
    assert first["enriched"] == 3
    posts = store.read_json(run, "posts.json")
    assert all("engagement_score" in p and "sentiment" in p for p in posts)
    # second call: nothing left to enrich
    second = it.trigger_enrichment_batch(run)
    assert second["enriched"] == 0


def test_enrichment_unknown_session():
    assert "error" in it.trigger_enrichment_batch("nope")
