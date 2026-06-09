"""HTML/PDF executive briefing generation for completed runs.

Expected run artifacts under data/runs/<run_id>/:
- run.json: topic, sources, timestamps, stop reason, metrics
- clusters.json: cluster labels, members, sentiment, top_posts
- posts.json: Post.to_dict() records keyed by id
"""
from __future__ import annotations

import html
import logging
import math
import shutil
import threading
import time
from pathlib import Path

from . import briefing_evidence
from .llm import chat_json
from .rag import _resolve_shot_url
from .store import read_json, run_dir, write_json


MAX_CLUSTERS = 4
QUOTES_PER_CLUSTER = 3
QUOTE_MAX_CHARS = 220
MAX_GRAPH_NODES = 14
MAX_CAPTURES = 40
CAPTURE_MAX_WIDTH = 720
CAPTURE_JPEG_QUALITY = 78

_LOG = logging.getLogger(__name__)


def build(run_id: str, *, with_pdf: bool = True,
          exec_summary: bool = True) -> dict:
    """Build a run briefing and return artifact paths.

    Returns {"html": Path, "pdf": Path|None, "manifest": Path}. The briefing
    directory is recreated on each call, making this operation idempotent.
    """
    run, clusters, posts_by_id, evidence = _load(run_id)

    out_dir = run_dir(run_id) / "briefing"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ranked_clusters = _rank_clusters(clusters, posts_by_id)
    selected = ranked_clusters[:MAX_CLUSTERS]
    quote_groups = [
        {"cluster": c, "quotes": _quotes(run_id, c, posts_by_id)}
        for c in selected
    ]
    captures = _captures(run_id, ranked_clusters, posts_by_id)
    summary = _exec_summary(run.get("topic", ""), selected) if exec_summary else ""
    evidence_top = briefing_evidence.render_top(evidence)
    evidence_bottom = briefing_evidence.render_bottom(evidence)

    ctx = {
        "run_id": run_id,
        "run": run,
        "clusters": selected,
        "chart_clusters": ranked_clusters,
        "quote_groups": quote_groups,
        "captures": captures,
        "summary": summary,
        "evidence_top": evidence_top,
        "evidence_bottom": evidence_bottom,
        "generated_at": int(time.time()),
    }

    html_path = out_dir / "briefing.html"
    pdf_path = out_dir / "briefing.pdf"
    manifest_path = out_dir / "briefing.json"

    html_path.write_text(_render_html(ctx), encoding="utf-8")
    pdf_ok = _render_pdf(html_path, pdf_path) if with_pdf else False

    manifest = {
        "generated_at": ctx["generated_at"],
        "run_id": run_id,
        "topic": run.get("topic", ""),
        "clusters_used": [c.get("id") for c in selected],
        "quotes": sum(len(g["quotes"]) for g in quote_groups),
        "captures": len(captures),
        "pdf": bool(pdf_ok),
        "exec_summary": bool(summary),
        "evidence": bool(evidence_top or evidence_bottom),
    }
    write_json(run_id, "briefing/briefing.json", manifest)
    return {
        "html": html_path,
        "pdf": pdf_path if pdf_ok else None,
        "manifest": manifest_path,
    }


def _load(run_id) -> tuple[dict, list[dict], dict[str, dict], dict]:
    run = read_json(run_id, "run.json")
    if not run:
        raise FileNotFoundError(f"run.json not found for run {run_id}")
    clusters = read_json(run_id, "clusters.json") or []
    posts = read_json(run_id, "posts.json") or []
    posts_by_id = {str(p.get("id")): p for p in posts if p.get("id")}
    evidence = read_json(run_id, "evidence.json") or {}
    return run, clusters, posts_by_id, evidence


def _rank_clusters(clusters, posts_by_id) -> list[dict]:
    def engagement(cluster: dict) -> int:
        total = 0
        for pid in cluster.get("top_posts") or []:
            post = posts_by_id.get(pid) or {}
            total += int(post.get("reactions") or 0)
            total += int(post.get("comments") or 0)
            total += int(post.get("shares") or 0)
        return total

    valid = [c for c in clusters if c.get("id") != -1]
    return sorted(
        valid,
        key=lambda c: (len(c.get("members") or []), engagement(c)),
        reverse=True,
    )


def _quotes(run_id: str, cluster, posts_by_id) -> list[dict]:
    out = []
    for pid in (cluster.get("top_posts") or [])[:QUOTES_PER_CLUSTER]:
        post = posts_by_id.get(pid)
        if not post:
            continue
        raw_text = str(post.get("text") or "").strip()
        cut = len(raw_text) > QUOTE_MAX_CHARS
        text = raw_text[:QUOTE_MAX_CHARS].rstrip()
        if cut:
            text += "…"
        raw = post.get("raw") if isinstance(post.get("raw"), dict) else {}
        shot_url = _relative_shot_url(run_id, raw.get("shot"))
        out.append({
            "id": pid,
            "text": text,
            "url": post.get("url"),
            "citation": _citation_line(post),
            "shot_url": shot_url,
        })
    return out


def _captures(run_id, clusters=None, posts_by_id=None) -> list[dict]:
    """Collect screenshot captures, downscale to JPEG, cap at MAX_CAPTURES.

    Original PNGs are 1-2MB each; embedding 50+ full-res in a PDF produces
    25-30MB files. Cached JPEGs in briefing/captures/ keep PDFs <5MB.
    """
    clusters = clusters or []
    posts_by_id = posts_by_id or {}
    out_dir = run_dir(run_id) / "briefing" / "captures"
    out_dir.mkdir(parents=True, exist_ok=True)

    captures: list[dict] = []
    seen_src: set[str] = set()
    cluster_label_by_shot: dict[str, str] = {}

    for cluster in clusters:
        label = str(cluster.get("label") or f"cluster {cluster.get('id')}")[:60]
        for pid in cluster.get("top_posts") or []:
            post = posts_by_id.get(pid) or {}
            raw = post.get("raw") if isinstance(post.get("raw"), dict) else {}
            shot = raw.get("shot")
            if shot:
                cluster_label_by_shot.setdefault(str(shot), label)

    shots_root = run_dir(run_id) / "shots"
    if not shots_root.exists():
        return captures

    cluster_first: list[tuple[Path, str, str]] = []
    leftover: list[tuple[Path, str, str]] = []
    for it_dir in sorted(p for p in shots_root.iterdir() if p.is_dir()):
        iter_label = it_dir.name.replace("_", " ")
        for shot_path in sorted(it_dir.glob("*.png")):
            label = cluster_label_by_shot.get(shot_path.name) or iter_label
            tag = (shot_path, label, it_dir.name)
            if shot_path.name in cluster_label_by_shot:
                cluster_first.append(tag)
            else:
                leftover.append(tag)

    for shot_path, label, iter_name in cluster_first + leftover:
        if len(captures) >= MAX_CAPTURES:
            break
        rel = f"{iter_name}__{shot_path.stem}.jpg"
        if rel in seen_src:
            continue
        dst = out_dir / rel
        if not dst.exists() and not _downscale(shot_path, dst):
            continue
        seen_src.add(rel)
        captures.append({
            "id": None,
            "src": f"captures/{rel}",
            "label": label,
        })
    return captures


def _downscale(src: Path, dst: Path) -> bool:
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            w, h = im.size
            if w > CAPTURE_MAX_WIDTH:
                new_h = int(h * CAPTURE_MAX_WIDTH / w)
                im = im.resize((CAPTURE_MAX_WIDTH, new_h), Image.LANCZOS)
            im.save(dst, format="JPEG", quality=CAPTURE_JPEG_QUALITY,
                    optimize=True, progressive=True)
        return True
    except Exception as e:
        _LOG.warning("capture downscale failed for %s: %s", src.name, e)
        return False


def _exec_summary(topic, clusters) -> str:
    lines = []
    for c in clusters:
        s = c.get("sentiment") or {}
        lines.append(
            f"- {c.get('label', 'cluster')}: "
            f"pos={float(s.get('pos') or 0):.2f}, "
            f"neu={float(s.get('neu') or 0):.2f}, "
            f"neg={float(s.get('neg') or 0):.2f}"
        )
    system = (
        "You are a senior intelligence analyst. Given a topic and cluster labels with "
        "sentiment ratios, write ONE paragraph (60-90 words) summarising the "
        "conversation landscape. No bullet points, no markdown. Output JSON: "
        '{"summary": "..."}'
    )
    user = f"Topic: {topic}\nClusters:\n" + "\n".join(lines)
    try:
        out = chat_json(system, user, max_tokens=180, stage="briefing")
    except Exception as e:
        _LOG.warning("briefing exec summary LLM failed: %s", e)
        return ""
    text = str(out.get("summary") or "").strip()
    if not text:
        _LOG.warning("briefing exec summary returned empty payload: %r", out)
    return text


def _render_html(ctx) -> str:
    run = ctx["run"]
    topic = _e(run.get("topic") or "Untitled run")
    started = _fmt_ts(run.get("started_at"))
    finished = _fmt_ts(run.get("finished_at"))
    duration = _duration(run.get("started_at"), run.get("finished_at"))
    sources = ", ".join(str(s) for s in run.get("sources") or [])
    metrics = run.get("metrics") or {}
    summary = _e(ctx.get("summary") or "")
    generated = _fmt_ts(ctx.get("generated_at"))
    chart_clusters = ctx.get("chart_clusters") or ctx["clusters"]

    quote_cards = "\n".join(_render_cluster_group(g) for g in ctx["quote_groups"])
    topic_graph = _topic_graph_svg(chart_clusters)
    sentiment_chart = _sentiment_chart_svg(chart_clusters)
    metrics_grid = _metrics_html(run, chart_clusters, ctx["captures"])
    captures = ""
    if ctx["captures"]:
        imgs = "\n".join(
            f'<figure><img src="{_a(t["src"])}" alt="{_a(t["label"])}">'
            f'<figcaption>{_e(t["label"])}</figcaption></figure>'
            for t in ctx["captures"]
        )
        captures = (
            '<section class="captures page-break"><h2>High-definition captures</h2>'
            f'<p class="section-note">{len(ctx["captures"])} saved screenshots from this run.</p>'
            f'<div>{imgs}</div></section>'
        )

    summary_block = f'<p class="summary">{summary}</p>' if summary else ""
    evidence_top = ctx.get("evidence_top") or ""
    evidence_bottom = ctx.get("evidence_bottom") or ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Briefing - {topic}</title>
  <style>
    @page {{ size: A4; margin: 14mm; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #0f172a; color: #e2e8f0; font-family: system-ui, -apple-system, sans-serif; font-size: 10.5px; line-height: 1.35; }}
    h1, h2, h3, p {{ margin: 0; }}
    h1 {{ font-size: 25px; line-height: 1.05; max-width: 78%; }}
    h2 {{ font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: #94a3b8; margin-bottom: 6px; border-left: 3px solid #22d3ee; padding-left: 8px; }}
    h3 {{ font-size: 12px; line-height: 1.2; margin-bottom: 5px; color: #e2e8f0; }}
    a {{ color: #22d3ee; text-decoration: none; }}
    section {{ margin: 12px 0; }}
    .top {{ display: flex; justify-content: space-between; gap: 18px; padding: 14px 16px; border-radius: 12px; background: linear-gradient(135deg, #22d3ee, #818cf8); color: #f8fafc; }}
    .top h1 {{ color: #f8fafc; }}
    .top h2 {{ color: rgba(248,250,252,.85); border-left: 3px solid rgba(248,250,252,.7); }}
    .meta {{ text-align: right; color: rgba(248,250,252,.92); font-size: 9.5px; min-width: 170px; }}
    .meta b {{ color: #f8fafc; }}
    .summary {{ margin: 10px 0 12px; color: #cbd5e1; font-size: 11px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 10px 0; }}
    .metric {{ border: 1px solid #334155; border-radius: 10px; padding: 8px; background: #1e293b; box-shadow: 0 0 0 1px #334155, 0 4px 18px rgba(34,211,238,.08); }}
    .metric b {{ display: block; font-size: 17px; color: #e2e8f0; }}
    .metric span {{ display: block; color: #94a3b8; font-size: 8.5px; text-transform: uppercase; letter-spacing: .06em; }}
    .visuals {{ display: grid; grid-template-columns: 1fr 1.15fr; gap: 10px; align-items: stretch; margin: 10px 0 12px; }}
    .visual-card {{ border: 1px solid #334155; border-radius: 10px; padding: 8px; background: #1e293b; break-inside: avoid; }}
    svg {{ display: block; width: 100%; height: auto; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 9px; }}
    .cluster {{ border: 1px solid #334155; border-radius: 10px; padding: 8px; background: #1e293b; break-inside: avoid; min-height: 153px; }}
    .cluster-head {{ display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; }}
    .count {{ white-space: nowrap; color: #94a3b8; font-size: 9px; }}
    .desc {{ color: #94a3b8; font-size: 9.5px; margin-bottom: 6px; min-height: 13px; }}
    .bar {{ display: flex; height: 6px; overflow: hidden; border-radius: 999px; background: #334155; margin: 5px 0 7px; }}
    .pos {{ background: #a3e635; }} .neu {{ background: #64748b; }} .neg {{ background: #fb7185; }}
    blockquote {{ margin: 0 0 6px; padding-left: 7px; border-left: 2px solid #334155; }}
    blockquote p {{ color: #e2e8f0; font-size: 9.7px; }}
    cite {{ display: block; font-style: normal; color: #94a3b8; font-size: 8.5px; margin-top: 2px; }}
    .captures {{ margin-top: 12px; border-top: 1px solid #334155; padding-top: 8px; }}
    .captures > div {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }}
    .section-note {{ color: #94a3b8; font-size: 9px; margin-bottom: 8px; }}
    figure {{ margin: 0; break-inside: avoid; }}
    figure img {{ width: 100%; max-height: 310px; object-fit: contain; object-position: top; border: 1px solid #334155; border-radius: 6px; display: block; background: #0b1220; }}
    figcaption {{ color: #94a3b8; font-size: 8.5px; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .foot {{ margin-top: 8px; color: #64748b; font-size: 8.5px; display: flex; justify-content: space-between; }}
    .page-break {{ break-before: page; }}
    .ev {{ margin: 12px 0; padding: 10px 12px; border: 1px solid #334155; border-radius: 10px; background: #1e293b; break-inside: avoid; }}
    .ev h3 {{ font-size: 10.5px; margin: 8px 0 4px; }}
    .ev ul {{ margin: 0 0 4px; padding-left: 16px; }}
    .ev li {{ color: #cbd5e1; margin-bottom: 2px; }}
    .ev p {{ color: #cbd5e1; }}
    .ev-plain {{ color: #e2e8f0; font-size: 11px; margin-bottom: 6px; }}
    .ev-conclusion {{ margin-top: 6px; color: #e2e8f0; font-weight: 600; }}
    .ev-ad {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    .ev-cols {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }}
    .ev-col {{ background: #0b1220; border: 1px solid #334155; border-radius: 8px; padding: 7px; }}
    .ev-col h3 {{ font-size: 9.5px; text-transform: uppercase; letter-spacing: .05em; margin: 0 0 4px; }}
    .ev-charts {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-start; margin-bottom: 8px; }}
    .ev-charts svg {{ width: auto; max-width: 100%; background: #0b1220; border-radius: 10px; }}
    .ev-cards {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
    .ev-screens {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    .ev-screen h3 {{ font-size: 11px; text-transform: uppercase; letter-spacing: .05em; }}
    .ev-claim {{ background: #0b1220; border: 1px solid #334155; border-radius: 8px; padding: 8px; break-inside: avoid; }}
    .ev-claim-head {{ display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }}
    .ev-badge {{ font-size: 8.5px; font-weight: 700; letter-spacing: .05em; }}
    .ev-pill {{ font-size: 8.5px; font-weight: 700; text-transform: uppercase; border: 1px solid currentColor; border-radius: 999px; padding: 1px 6px; }}
    .ev-conf {{ margin-left: auto; color: #94a3b8; font-size: 8.5px; }}
    .ev-claim-text {{ color: #e2e8f0; font-size: 10px; margin-bottom: 5px; }}
    .ev-minis {{ display: grid; gap: 2px; margin-bottom: 5px; }}
    .ev-mini {{ display: flex; align-items: center; gap: 6px; }}
    .ev-mini-label {{ width: 72px; color: #94a3b8; font-size: 8px; }}
    .ev-mini-track {{ flex: 1; height: 5px; border-radius: 999px; background: #334155; overflow: hidden; }}
    .ev-mini-fill {{ display: block; height: 5px; border-radius: 999px; }}
    .ev-reason {{ color: #94a3b8; font-size: 9px; margin-bottom: 5px; }}
    .ev-tags {{ display: flex; flex-wrap: wrap; gap: 4px; }}
    .ev-tag {{ font-size: 8px; color: #cbd5e1; background: #1e293b; border: 1px solid #334155; border-radius: 999px; padding: 1px 6px; }}
  </style>
</head>
<body>
  <header class="top">
    <div>
      <h2>Executive briefing</h2>
      <h1>{topic}</h1>
    </div>
    <div class="meta">
      <div><b>Run</b> {_e(ctx["run_id"])}</div>
      <div><b>Sources</b> {_e(sources or "unknown")}</div>
      <div><b>Started</b> {started}</div>
      <div><b>Finished</b> {finished}</div>
      <div><b>Duration</b> {duration}</div>
      <div><b>Stop</b> {_e(run.get("stop_reason") or "unknown")}</div>
      <div><b>Posts / clusters</b> {_e(metrics.get("posts", 0))} / {_e(metrics.get("clusters", 0))}</div>
    </div>
  </header>
  {summary_block}
  {evidence_top}
  <section>
    <h2>Metrics</h2>
    <div class="metrics">{metrics_grid}</div>
  </section>
  <section class="visuals">
    <div class="visual-card">
      <h2>Topic graph</h2>
      {topic_graph}
    </div>
    <div class="visual-card">
      <h2>Sentiment by cluster</h2>
      {sentiment_chart}
    </div>
  </section>
  {evidence_bottom}
  <section class="grid">
    {quote_cards}
  </section>
  {captures}
  <footer class="foot">
    <span>Generated {generated}</span>
    <span>Top posts are influence-ranked from the run artifacts.</span>
  </footer>
</body>
</html>
"""


def _metrics_html(run: dict, clusters: list[dict], captures: list[dict]) -> str:
    metrics = run.get("metrics") or {}
    posts = metrics.get("posts", 0)
    queries = len(run.get("queries") or [])
    sources = len(run.get("sources") or [])
    clusters_n = len([c for c in clusters if c.get("id") != -1])
    items = [
        ("Posts", posts),
        ("Clusters", clusters_n),
        ("Queries", queries),
        ("Sources", sources),
        ("Captures", len(captures)),
        ("Stop reason", run.get("stop_reason") or "unknown"),
        ("Started", _fmt_ts(run.get("started_at"))),
        ("Duration", _duration(run.get("started_at"), run.get("finished_at"))),
    ]
    return "\n".join(
        f'<div class="metric"><span>{_e(label)}</span><b>{_e(value)}</b></div>'
        for label, value in items
    )


def _topic_graph_svg(clusters: list[dict]) -> str:
    nodes = [c for c in clusters if c.get("id") != -1 and c.get("centroid")]
    nodes = nodes[:MAX_GRAPH_NODES]
    if not nodes:
        return '<div class="section-note">No centroid data available for a topic graph.</div>'

    width, height = 520, 300
    cx, cy = width / 2, height / 2
    radius = min(width, height) * 0.34
    positioned = []
    for i, cluster in enumerate(nodes):
        angle = -math.pi / 2 + (2 * math.pi * i / max(len(nodes), 1))
        size = 14 + min(18, math.sqrt(max(1, len(cluster.get("members") or []))) * 2.6)
        positioned.append({
            "cluster": cluster,
            "x": cx + radius * math.cos(angle),
            "y": cy + radius * math.sin(angle),
            "r": size,
        })

    edges = []
    best_edge = None
    best_sim = -1.0
    for i, a in enumerate(positioned):
        for b in positioned[i + 1:]:
            sim = _cosine(a["cluster"].get("centroid") or [], b["cluster"].get("centroid") or [])
            if sim > best_sim:
                best_sim = sim
                best_edge = (a, b, sim)
            if sim >= 0.35:
                edges.append((a, b, sim))
    if not edges and best_edge:
        edges.append(best_edge)

    edge_svg = "\n".join(
        '<line class="edge" '
        f'x1="{a["x"]:.1f}" y1="{a["y"]:.1f}" x2="{b["x"]:.1f}" y2="{b["y"]:.1f}" '
        f'stroke="#475569" stroke-width="{1 + max(0, sim) * 3:.1f}" '
        f'opacity="{0.22 + max(0, sim) * 0.45:.2f}" />'
        for a, b, sim in edges
    )
    node_svg = "\n".join(_topic_node_svg(n) for n in positioned)
    return f"""<svg class="topic-graph" viewBox="0 0 {width} {height}" role="img" aria-label="Topic graph">
  <rect x="0" y="0" width="{width}" height="{height}" rx="12" fill="#f8fafc" />
  {edge_svg}
  {node_svg}
</svg>"""


def _topic_node_svg(node: dict) -> str:
    c = node["cluster"]
    label = str(c.get("label") or f"cluster {c.get('id')}")
    short = label[:24] + ("..." if len(label) > 24 else "")
    members = len(c.get("members") or [])
    return f"""<g>
  <circle cx="{node["x"]:.1f}" cy="{node["y"]:.1f}" r="{node["r"]:.1f}" fill="#60a5fa" opacity="0.92" />
  <circle cx="{node["x"]:.1f}" cy="{node["y"]:.1f}" r="{node["r"] + 4:.1f}" fill="none" stroke="#bfdbfe" stroke-width="2" />
  <text x="{node["x"]:.1f}" y="{node["y"] + node["r"] + 15:.1f}" text-anchor="middle" font-size="10" fill="#334155">{_e(short)}</text>
  <text x="{node["x"]:.1f}" y="{node["y"] + 3:.1f}" text-anchor="middle" font-size="10" font-weight="700" fill="#0f172a">{members}</text>
</g>"""


def _sentiment_chart_svg(clusters: list[dict]) -> str:
    rows = [c for c in clusters if c.get("id") != -1]
    if not rows:
        return '<div class="section-note">No sentiment data available.</div>'
    bar_x = 170
    bar_w = 320
    row_h = 27
    width = 520
    height = 26 + row_h * len(rows)
    parts = [
        f'<svg class="sentiment-chart" viewBox="0 0 {width} {height}" role="img" aria-label="Sentiment by cluster">',
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="12" fill="#f8fafc" />',
    ]
    for i, c in enumerate(rows):
        y = 22 + i * row_h
        s = c.get("sentiment") or {}
        pos = _ratio(s.get("pos"))
        neu = _ratio(s.get("neu"))
        neg = _ratio(s.get("neg"))
        total = pos + neu + neg
        if total <= 0:
            pos, neu, neg = 0.0, 1.0, 0.0
        else:
            pos, neu, neg = pos / total, neu / total, neg / total
        label = str(c.get("label") or f"cluster {c.get('id')}")
        short = label[:28] + ("..." if len(label) > 28 else "")
        pos_w = bar_w * pos
        neu_w = bar_w * neu
        neg_w = bar_w * neg
        parts.extend([
            f'<text x="12" y="{y + 12}" font-size="10" fill="#334155">{_e(short)}</text>',
            f'<rect x="{bar_x}" y="{y}" width="{bar_w}" height="15" rx="7.5" fill="#e5e7eb" />',
            f'<rect x="{bar_x}" y="{y}" width="{pos_w:.1f}" height="15" rx="7.5" fill="#16a34a" />',
            f'<rect x="{bar_x + pos_w:.1f}" y="{y}" width="{neu_w:.1f}" height="15" fill="#94a3b8" />',
            f'<rect x="{bar_x + pos_w + neu_w:.1f}" y="{y}" width="{neg_w:.1f}" height="15" rx="7.5" fill="#dc2626" />',
            f'<text x="{bar_x + bar_w + 8}" y="{y + 12}" font-size="9" fill="#64748b">{round(pos * 100)}/{round(neu * 100)}/{round(neg * 100)}</text>',
        ])
    parts.append("</svg>")
    return "\n".join(parts)


def _render_pdf(html_path: Path, pdf_path: Path) -> bool:
    """Render the briefing to PDF, trying engines in order of fidelity.

    WeasyPrint is preferred but needs GTK/Pango/cairo native libraries that are
    absent on stock Windows, where importing it raises OSError (not ImportError).
    Chromium via Playwright ships those bindings internally and is already a
    project dependency for the scraper, so it is a portable fallback.
    """
    if _render_pdf_weasyprint(html_path, pdf_path):
        return True
    return _render_pdf_chromium(html_path, pdf_path)


def _render_pdf_weasyprint(html_path: Path, pdf_path: Path) -> bool:
    try:
        from weasyprint import HTML
    except Exception as e:  # OSError on Windows w/o GTK; ImportError if absent
        _LOG.info("weasyprint unavailable, trying chromium fallback: %s", e)
        return False
    try:
        HTML(
            filename=str(html_path),
            base_url=str(html_path.parent.resolve()),
        ).write_pdf(str(pdf_path))
    except Exception as e:
        _LOG.warning("weasyprint PDF render failed, trying chromium: %s", e)
        return False
    return True


def _render_pdf_chromium(html_path: Path, pdf_path: Path) -> bool:
    """Render via headless Chromium in a dedicated thread.

    The thread isolates sync_playwright from any running asyncio loop in the
    caller, which would otherwise raise "sync API inside asyncio loop".
    """
    result = {"ok": False}

    def _work() -> None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            _LOG.warning("playwright unavailable for PDF fallback: %s", e)
            return
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                try:
                    page = browser.new_page()
                    page.goto(html_path.resolve().as_uri(),
                              wait_until="networkidle")
                    page.pdf(
                        path=str(pdf_path),
                        format="A4",
                        print_background=True,
                        margin={"top": "12mm", "bottom": "12mm",
                                "left": "10mm", "right": "10mm"},
                    )
                finally:
                    browser.close()
            result["ok"] = True
        except Exception as e:
            _LOG.warning("chromium PDF render failed: %s", e)

    t = threading.Thread(target=_work)
    t.start()
    t.join()
    return result["ok"]


def _render_cluster_group(group: dict) -> str:
    c = group["cluster"]
    s = c.get("sentiment") or {}
    pos = max(0.0, min(1.0, float(s.get("pos") or 0.0)))
    neu = max(0.0, min(1.0, float(s.get("neu") or 0.0)))
    neg = max(0.0, min(1.0, float(s.get("neg") or 0.0)))
    label = str(c.get("label") or f"cluster {c.get('id')}")[:60]
    desc = str(c.get("desc") or "")[:130]
    quotes = "\n".join(_render_quote(q) for q in group["quotes"])
    return f"""<article class="cluster">
  <div class="cluster-head">
    <h3>{_e(label)}</h3>
    <span class="count">{len(c.get("members") or [])} posts</span>
  </div>
  <p class="desc">{_e(desc)}</p>
  <div class="bar" aria-label="sentiment">
    <span class="pos" style="width:{pos * 100:.1f}%"></span>
    <span class="neu" style="width:{neu * 100:.1f}%"></span>
    <span class="neg" style="width:{neg * 100:.1f}%"></span>
  </div>
  {quotes}
</article>"""


def _render_quote(q: dict) -> str:
    text = _e(q["text"])
    if q.get("url"):
        text = f'<a href="{_a(q["url"])}">{text}</a>'
    shot = f' · shot: {_e(q["shot_url"])}' if q.get("shot_url") else ""
    return (
        "<blockquote>"
        f"<p>{text}</p>"
        f"<cite>{_e(q['citation'])}{shot}</cite>"
        "</blockquote>"
    )


def _citation_line(post: dict) -> str:
    source = post.get("source") or "unknown"
    author = post.get("author") or "anon"
    reactions = int(post.get("reactions") or 0)
    comments = int(post.get("comments") or 0)
    shares = int(post.get("shares") or 0)
    return f"{source} · {author} · ❤ {reactions} 💬 {comments} ↻ {shares}"


def _relative_shot_url(run_id: str, shot_name: str | None) -> str | None:
    if not shot_name:
        return None
    resolved = _resolve_shot_url(run_id, shot_name)
    if not resolved:
        return None
    prefix = f"/shots/{run_id}/"
    if not resolved.startswith(prefix):
        return resolved
    return "../shots/" + resolved[len(prefix):]


def _fmt_ts(value) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(value)))
    except Exception:
        return "unknown"


def _duration(start, end) -> str:
    try:
        seconds = max(0, int(end) - int(start))
    except Exception:
        return "unknown"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _cosine(a, b) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(float(a[i]) * float(b[i]) for i in range(n))
    na = math.sqrt(sum(float(a[i]) ** 2 for i in range(n)))
    nb = math.sqrt(sum(float(b[i]) ** 2 for i in range(n)))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def _ratio(value) -> float:
    try:
        return max(0.0, float(value))
    except Exception:
        return 0.0


def _e(value) -> str:
    return html.escape(str(value), quote=False)


def _a(value) -> str:
    return html.escape(str(value), quote=True)
