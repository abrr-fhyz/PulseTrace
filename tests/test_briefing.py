import json
import re
import shutil
import struct
import zlib
from pathlib import Path
from unittest.mock import patch

import pytest

from lib import briefing, store


def _png_rgb(rgb, width=640, height=360):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    row = b"\x00" + bytes(rgb) * width
    raw = row * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


PNG_RED = _png_rgb((220, 38, 38))
PNG_GREEN = _png_rgb((22, 163, 74))
PNG_BLUE = _png_rgb((37, 99, 235))


def _write_sample_run(tmp_path, monkeypatch, run_id="briefing-test"):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    d = store.run_dir(run_id)
    (d / "shots" / "iter_1").mkdir(parents=True)
    (d / "shots" / "iter_1" / "shot-a.png").write_bytes(PNG_RED)
    (d / "shots" / "iter_1" / "shot-b.png").write_bytes(PNG_GREEN)
    (d / "shots" / "iter_1" / "shot-c.png").write_bytes(PNG_BLUE)

    posts = []
    for i in range(10):
        raw = {}
        if i == 2:
            raw["shot"] = "shot-a.png"
        if i == 4:
            raw["shot"] = "shot-b.png"
        posts.append({
            "id": f"facebook:p{i}",
            "source": "facebook",
            "text": ("long text " * 40) if i == 2 else f"post {i} text",
            "author": f"author{i}" if i % 2 else None,
            "url": f"https://example.test/{i}" if i % 3 == 0 else None,
            "ts": 1780000000 + i,
            "reactions": i * 10,
            "comments": i,
            "shares": i // 2,
            "raw": raw,
        })

    clusters = [
        {
            "id": 0,
            "label": "Small but engaged",
            "desc": "two posts",
            "members": ["facebook:p8", "facebook:p9"],
            "sentiment": {"pos": 0.6, "neu": 0.2, "neg": 0.2},
            "centroid": [1.0, 0.0],
            "top_posts": ["facebook:p9", "facebook:p8"],
        },
        {
            "id": 1,
            "label": "Large low engagement",
            "desc": "four posts",
            "members": ["facebook:p0", "facebook:p1", "facebook:p2", "facebook:p3"],
            "sentiment": {"pos": 0.1, "neu": 0.7, "neg": 0.2},
            "centroid": [0.8, 0.2],
            "top_posts": ["facebook:p2", "facebook:p1", "facebook:p0"],
        },
        {
            "id": 2,
            "label": "Large high engagement",
            "desc": "four posts too",
            "members": ["facebook:p4", "facebook:p5", "facebook:p6", "facebook:p7"],
            "sentiment": {"pos": 0.2, "neu": 0.3, "neg": 0.5},
            "centroid": [0.0, 1.0],
            "top_posts": ["facebook:p7", "facebook:p6", "facebook:p4"],
        },
        {
            "id": -1,
            "label": "Noise",
            "desc": "",
            "members": ["facebook:p9"],
            "sentiment": {"pos": 0, "neu": 1, "neg": 0},
            "centroid": [0.1, 0.1],
            "top_posts": ["facebook:p9"],
        },
    ]
    run = {
        "id": run_id,
        "topic": "Test fixture Buffalo policy debate",
        "sources": ["facebook"],
        "started_at": 1780000000,
        "finished_at": 1780000125,
        "queries": [{"q": "buffalo", "source": "facebook", "iter": 1}],
        "stop_reason": "iters",
        "metrics": {"posts": len(posts), "clusters": 3},
    }
    (d / "run.json").write_text(json.dumps(run))
    (d / "posts.json").write_text(json.dumps(posts))
    (d / "clusters.json").write_text(json.dumps(clusters))
    return run_id, run, clusters, {p["id"]: p for p in posts}


def _artifact_pdf_path(run):
    topic = (run.get("topic") or "").strip()
    if not topic:
        queries = run.get("queries") or []
        topic = str((queries[0] or {}).get("q") or "briefing") if queries else "briefing"
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-") or "briefing"
    return Path("test_artifacts") / f"briefing-{slug}.pdf"


def test_select_clusters_orders_by_size_then_engagement(tmp_path, monkeypatch):
    _, _, clusters, posts_by_id = _write_sample_run(tmp_path, monkeypatch)
    selected = briefing._rank_clusters(clusters, posts_by_id)[:briefing.MAX_CLUSTERS]
    assert [c["id"] for c in selected] == [2, 1, 0]


def test_quotes_truncate_and_resolve_relative_shot(tmp_path, monkeypatch):
    run_id, _, clusters, posts_by_id = _write_sample_run(tmp_path, monkeypatch)
    quotes = briefing._quotes(run_id, clusters[1], posts_by_id)
    assert quotes[0]["text"].endswith("…")
    assert len(quotes[0]["text"]) <= briefing.QUOTE_MAX_CHARS + 1
    assert quotes[0]["shot_url"] == "../shots/iter_1/shot-a.png"
    assert "facebook · anon · ❤ 20" in quotes[0]["citation"]


def test_captures_collect_all_saved_screenshots(tmp_path, monkeypatch):
    run_id, _, clusters, posts_by_id = _write_sample_run(tmp_path, monkeypatch)
    captures = briefing._captures(run_id, clusters, posts_by_id)
    assert [t["src"] for t in captures] == [
        "captures/iter_1__shot-a.jpg",
        "captures/iter_1__shot-b.jpg",
        "captures/iter_1__shot-c.jpg",
    ]
    assert captures[2]["label"] == "iter 1"
    for t in captures:
        p = store.run_dir(run_id) / "briefing" / t["src"]
        assert p.exists() and p.stat().st_size > 0


def test_graphical_sections_render_svg(tmp_path, monkeypatch):
    _, _, clusters, posts_by_id = _write_sample_run(tmp_path, monkeypatch)
    selected = briefing._rank_clusters(clusters, posts_by_id)[:briefing.MAX_CLUSTERS]
    topic_graph = briefing._topic_graph_svg(selected)
    sentiment = briefing._sentiment_chart_svg(selected)
    assert '<svg class="topic-graph"' in topic_graph
    assert 'class="edge"' in topic_graph
    assert "Large high engagement" in topic_graph
    assert '<svg class="sentiment-chart"' in sentiment
    assert "Small but engaged" in sentiment


def test_build_writes_html_and_manifest(tmp_path, monkeypatch):
    run_id, _, _, _ = _write_sample_run(tmp_path, monkeypatch)
    out = briefing.build(run_id, with_pdf=False, exec_summary=False)
    assert out["pdf"] is None
    assert out["html"].exists()
    html = out["html"].read_text()
    assert "Buffalo policy debate" in html
    assert "Large high engagement" in html
    assert "Topic graph" in html
    assert "Metrics" in html
    assert "Sentiment by cluster" in html
    assert '<svg class="topic-graph"' in html
    assert '<svg class="sentiment-chart"' in html
    assert '<img src="captures/iter_1__shot-a.jpg"' in html
    assert '<img src="captures/iter_1__shot-c.jpg"' in html
    manifest = json.loads(out["manifest"].read_text())
    assert manifest["clusters_used"] == [2, 1, 0]
    assert manifest["quotes"] == 8
    assert manifest["captures"] == 3
    assert manifest["pdf"] is False


def test_exec_summary_failure_still_builds(tmp_path, monkeypatch):
    run_id, _, _, _ = _write_sample_run(tmp_path, monkeypatch)
    with patch("lib.briefing.chat_json", side_effect=RuntimeError("llm down")):
        out = briefing.build(run_id, with_pdf=False, exec_summary=True)
    assert out["html"].exists()
    manifest = json.loads(out["manifest"].read_text())
    assert manifest["exec_summary"] is False


def test_exec_summary_success_is_rendered(tmp_path, monkeypatch):
    run_id, _, _, _ = _write_sample_run(tmp_path, monkeypatch)
    with patch("lib.briefing.chat_json", return_value={"summary": "stub summary"}):
        out = briefing.build(run_id, with_pdf=False, exec_summary=True)
    assert "stub summary" in out["html"].read_text()
    manifest = json.loads(out["manifest"].read_text())
    assert manifest["exec_summary"] is True


def test_http_briefing_routes(tmp_path, monkeypatch):
    run_id, _, _, _ = _write_sample_run(tmp_path, monkeypatch)
    with patch("lib.briefing.chat_json", return_value={"summary": "stub summary"}):
        import server

        client = server.app.test_client()
        html_res = client.get(f"/run/{run_id}/briefing/html")
        assert html_res.status_code == 200
        assert b"Buffalo policy debate" in html_res.data

        manifest_res = client.get(f"/run/{run_id}/briefing/manifest")
        assert manifest_res.status_code == 200
        assert manifest_res.json["run_id"] == run_id

        missing = client.get("/run/missing-run/briefing/html")
        assert missing.status_code == 500
        assert "error" in missing.json


def test_http_pdf_returns_501_when_builder_produces_no_pdf(tmp_path, monkeypatch):
    run_id, _, _, _ = _write_sample_run(tmp_path, monkeypatch)
    import server

    def fake_build(rid, with_pdf=True, exec_summary=True):
        d = store.run_dir(rid) / "briefing"
        d.mkdir(parents=True, exist_ok=True)
        (d / "briefing.html").write_text("<html></html>")
        return {"html": d / "briefing.html", "pdf": None, "manifest": d / "briefing.json"}

    monkeypatch.setattr(server, "build_briefing", fake_build)
    res = server.app.test_client().get(f"/run/{run_id}/briefing/pdf")
    assert res.status_code == 501
    assert "PDF unavailable" in res.json["error"]


_EVIDENCE_BASE = {
    "exec_summary": {
        "plain_topic": "Mid-range phone reviews",
        "key_findings": ["battery lasts all day"],
        "agreements": ["fast charging"],
        "disagreements": ["camera in low light"],
        "conclusion": "solid value pick",
    },
    "topic_overview": "Discussion centers on value for money.",
    "community_consensus": {
        "top_praise": ["battery"],
        "top_criticism": ["camera"],
        "misconceptions": ["overheats"],
        "uncertainties": ["long-term durability"],
    },
    "claims": [
        {"text": "Battery lasts all day", "side": "pro", "confidence": 0.8,
         "evidence_strength": "strong", "reasoning": "corroborating posts",
         "source_categories": ["forums"], "cluster_ids": [0],
         "ranking": {"credibility": 0.8, "data_quality": 0.6, "sample_size": 0.5,
                     "recency": 0.7, "corroboration": 0.66}},
        {"text": "Camera weak in low light", "side": "con", "confidence": 0.4,
         "evidence_strength": "weak", "reasoning": "few complaints",
         "source_categories": ["social"], "cluster_ids": [1],
         "ranking": {"credibility": 0.3, "data_quality": 0.4, "sample_size": 0.2,
                     "recency": 0.5, "corroboration": 0.3}},
    ],
    "screen_a": [
        {"text": "Battery lasts all day", "side": "pro", "confidence": 0.8,
         "evidence_strength": "strong", "reasoning": "corroborating posts",
         "source_categories": ["forums"], "cluster_ids": [0],
         "ranking": {"credibility": 0.8, "data_quality": 0.6, "sample_size": 0.5,
                     "recency": 0.7, "corroboration": 0.66}},
    ],
    "screen_b": [
        {"text": "Camera weak in low light", "side": "con", "confidence": 0.4,
         "evidence_strength": "weak", "reasoning": "few complaints",
         "source_categories": ["social"], "cluster_ids": [1],
         "ranking": {"credibility": 0.3, "data_quality": 0.4, "sample_size": 0.2,
                     "recency": 0.5, "corroboration": 0.3}},
    ],
    "uncertainty": ["sample skew toward enthusiasts"],
    "final_assessment": "Evidence mostly supports the view.",
}


def test_briefing_includes_evidence_when_opinion(tmp_path, monkeypatch):
    run_id, _, _, _ = _write_sample_run(tmp_path, monkeypatch)
    ev = {**_EVIDENCE_BASE, "opinion": "this phone is great"}
    (store.run_dir(run_id) / "evidence.json").write_text(json.dumps(ev))
    with patch("lib.briefing.chat_json", return_value={"summary": "stub summary"}):
        out = briefing.build(run_id, with_pdf=False)
    html = out["html"].read_text()
    assert "Executive" in html
    assert "ev-claims" in html
    manifest = json.loads(out["manifest"].read_text())
    assert manifest["evidence"] is True


def test_briefing_omits_evidence_when_opinion_none(tmp_path, monkeypatch):
    run_id, _, _, _ = _write_sample_run(tmp_path, monkeypatch)
    ev = {**_EVIDENCE_BASE, "opinion": None}
    (store.run_dir(run_id) / "evidence.json").write_text(json.dumps(ev))
    with patch("lib.briefing.chat_json", return_value={"summary": "stub summary"}):
        out = briefing.build(run_id, with_pdf=False)
    html = out["html"].read_text()
    assert "ev-claims" not in html
    manifest = json.loads(out["manifest"].read_text())
    assert manifest["evidence"] is False


def test_pdf_render_gated(tmp_path, monkeypatch):
    pytest.importorskip("weasyprint")
    run_id, run, _, _ = _write_sample_run(tmp_path, monkeypatch)
    out = briefing.build(run_id, with_pdf=True, exec_summary=False)
    assert out["pdf"] is not None
    data = out["pdf"].read_bytes()
    assert data.startswith(b"%PDF-")
    artifact = _artifact_pdf_path(run)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out["pdf"], artifact)
    assert artifact.exists()


def test_weasyprint_oserror_does_not_raise(tmp_path):
    # Windows without GTK: `import weasyprint` raises OSError, not ImportError.
    html_path = tmp_path / "b.html"
    html_path.write_text("<html><body>x</body></html>")
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "weasyprint":
            raise OSError("cannot load library 'libgobject-2.0-0.dll'")
        return real_import(name, *a, **k)

    with patch("builtins.__import__", side_effect=fake_import):
        assert briefing._render_pdf_weasyprint(html_path, tmp_path / "b.pdf") is False


def test_render_pdf_falls_back_to_chromium(tmp_path):
    html_path = tmp_path / "b.html"
    pdf_path = tmp_path / "b.pdf"
    html_path.write_text("<html><body>x</body></html>")

    def fake_chromium(h, p):
        Path(p).write_bytes(b"%PDF-fake")
        return True

    with patch("lib.briefing._render_pdf_weasyprint", return_value=False), \
         patch("lib.briefing._render_pdf_chromium", side_effect=fake_chromium):
        assert briefing._render_pdf(html_path, pdf_path) is True
    assert pdf_path.read_bytes().startswith(b"%PDF-")


def test_render_pdf_false_when_both_engines_fail(tmp_path):
    html_path = tmp_path / "b.html"
    html_path.write_text("<html><body>x</body></html>")
    with patch("lib.briefing._render_pdf_weasyprint", return_value=False), \
         patch("lib.briefing._render_pdf_chromium", return_value=False):
        assert briefing._render_pdf(html_path, tmp_path / "b.pdf") is False


def test_render_pdf_chromium_produces_valid_pdf(tmp_path):
    pytest.importorskip("playwright")
    html_path = tmp_path / "b.html"
    pdf_path = tmp_path / "b.pdf"
    html_path.write_text(
        "<html><body><h1>hi</h1>"
        "<div style='background:#0a0;width:80px;height:10px'></div>"
        "</body></html>"
    )
    if not briefing._render_pdf_chromium(html_path, pdf_path):
        pytest.skip("chromium browser not installed (run 'playwright install chromium')")
    assert pdf_path.read_bytes().startswith(b"%PDF-")
