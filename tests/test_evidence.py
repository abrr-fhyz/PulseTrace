from __future__ import annotations
import json
from unittest.mock import patch
from lib import evidence
from lib.store import run_dir, write_json


def _seed_run(tmp_root, run_id, with_posts=True):
    write_json(run_id, "run.json", {"id": run_id, "topic": "Elden Ring", "sources": ["reddit"]})
    write_json(run_id, "clusters.json", [
        {"id": 0, "label": "Combat praise", "desc": "loved", "centroid": [],
         "members": ["reddit:1", "reddit:2"], "sentiment": {"pos": 0.8, "neu": 0.1, "neg": 0.1},
         "top_posts": ["reddit:1"]},
        {"id": 1, "label": "Too hard", "desc": "difficulty", "centroid": [],
         "members": ["hn:3"], "sentiment": {"pos": 0.1, "neu": 0.2, "neg": 0.7},
         "top_posts": ["hn:3"]},
    ])
    write_json(run_id, "posts.json", [
        {"id": "reddit:1", "source": "reddit", "text": "combat is amazing", "ts": 100,
         "reactions": 10, "comments": 4, "shares": 1, "author": None, "url": None, "raw": {}},
        {"id": "reddit:2", "source": "reddit", "text": "bosses are fair", "ts": 90,
         "reactions": 5, "comments": 2, "shares": 0, "author": None, "url": None, "raw": {}},
        {"id": "hn:3", "source": "hn", "text": "way too punishing for newcomers", "ts": 80,
         "reactions": 8, "comments": 6, "shares": 0, "author": None, "url": None, "raw": {}},
    ])


_FAKE_LLM = {
    "exec_summary": {"plain_topic": "An action RPG.", "key_findings": ["loved combat"],
                     "agreements": ["combat depth"], "disagreements": ["difficulty"],
                     "conclusion": "Polarizing but acclaimed."},
    "topic_overview": "Open-world soulslike.",
    "community_consensus": {"top_praise": ["combat"], "top_criticism": ["difficulty"],
                            "misconceptions": ["no story"], "uncertainties": ["performance"]},
    "uncertainty": ["frame pacing on old GPUs"],
    "final_assessment": "Strong game; difficulty is a real barrier.",
    "claims": [
        {"text": "Combat is deep and rewarding", "side": "pro", "reasoning": "many praise it",
         "llm_confidence": 0.8, "cluster_ids": [0]},
        {"text": "Punishing difficulty deters newcomers", "side": "con",
         "reasoning": "repeated complaint", "llm_confidence": 0.6, "cluster_ids": [1]},
    ],
}


def test_build_writes_evidence_json_with_screens(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.store.ROOT", tmp_path / "runs")
    run_id = "t1"
    _seed_run(tmp_path, run_id)
    with patch("lib.evidence.chat_json", return_value=_FAKE_LLM):
        out = evidence.build(run_id, opinion="I want to play Elden Ring")

    assert out["opinion"] == "I want to play Elden Ring"
    assert len(out["claims"]) == 2
    pro = [c for c in out["claims"] if c["side"] == "pro"][0]
    assert 0.0 <= pro["confidence"] <= 1.0
    assert pro["evidence_strength"] in {"weak", "moderate", "strong"}
    assert set(pro["ranking"]) == {"credibility", "data_quality", "sample_size", "recency", "corroboration"}
    assert pro["source_categories"]
    assert len(out["screen_a"]) == 1 and len(out["screen_b"]) == 1
    assert out["exec_summary"]["plain_topic"]
    saved = json.loads((run_dir(run_id) / "evidence.json").read_text())
    assert saved["final_assessment"]


def test_build_neutral_when_no_opinion(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.store.ROOT", tmp_path / "runs")
    run_id = "t2"
    _seed_run(tmp_path, run_id)
    with patch("lib.evidence.chat_json", return_value=_FAKE_LLM):
        out = evidence.build(run_id, opinion=None)
    assert out["opinion"] is None
    assert out["screen_a"] == [] and out["screen_b"] == []
    assert all(c["side"] == "neutral" for c in out["claims"])


def test_build_handles_string_cluster_ids(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.store.ROOT", tmp_path / "runs")
    run_id = "t4"
    _seed_run(tmp_path, run_id)
    llm = {**_FAKE_LLM, "claims": [
        {"text": "Combat is deep", "side": "pro", "reasoning": "r",
         "llm_confidence": 0.8, "cluster_ids": ["0"]},
    ]}
    with patch("lib.evidence.chat_json", return_value=llm):
        out = evidence.build(run_id, opinion="I want to play it")
    claim = out["claims"][0]
    assert claim["cluster_ids"] == [0]
    assert claim["source_categories"] != ["unknown"]


def test_build_survives_llm_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.store.ROOT", tmp_path / "runs")
    run_id = "t3"
    _seed_run(tmp_path, run_id)
    with patch("lib.evidence.chat_json", side_effect=RuntimeError("boom")):
        out = evidence.build(run_id, opinion="x")
    assert out["claims"] == []
    assert out["exec_summary"]["plain_topic"] == ""
