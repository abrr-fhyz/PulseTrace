"""Opinion-aware evidence layer rendered to static dark-theme HTML/SVG.

Pure render functions for the briefing PDF: exec summary + topic overview
(``render_top``) and community consensus, evidence claims, pro/con screens,
uncertainty, final assessment (``render_bottom``). SVG charts are static — the
PDF engine (WeasyPrint) runs no JS. All blocks render only when an opinion is
set; everything degrades gracefully on empty / missing input.
"""
from __future__ import annotations

import html
import math

AXES = ("credibility", "data_quality", "sample_size", "recency", "corroboration")
_AXIS_LABEL = {
    "credibility": "Credibility", "data_quality": "Data quality",
    "sample_size": "Sample size", "recency": "Recency",
    "corroboration": "Corroboration",
}

_CYAN = "#22d3ee"
_LIME = "#a3e635"
_MAGENTA = "#e879f9"
_SLATE = "#64748b"
_AMBER = "#fbbf24"
_PANEL2 = "#0b1220"
_BORDER = "#334155"
_TRACK = "#334155"
_TEXT = "#cbd5e1"
_MUTED = "#94a3b8"

_STRENGTH_COLOR = {"strong": _LIME, "moderate": _CYAN, "weak": _SLATE}
_SIDE_COLOR = {"pro": _LIME, "con": _MAGENTA, "neutral": _SLATE}


def render_top(evidence: dict) -> str:
    if not evidence or not evidence.get("opinion"):
        return ""
    es = evidence.get("exec_summary") or {}
    summary = _exec_summary_html(es)
    overview = _e(evidence.get("topic_overview") or "")
    overview_block = (
        f'<section class="ev ev-overview"><h2>Topic overview</h2>'
        f'<p>{overview}</p></section>' if overview else ""
    )
    return summary + overview_block


def render_bottom(evidence: dict) -> str:
    if not evidence or not evidence.get("opinion"):
        return ""
    parts = [
        _consensus_html(evidence.get("community_consensus") or {}),
        _claims_html(evidence.get("claims") or []),
        _procon_html(evidence.get("screen_a") or [], evidence.get("screen_b") or []),
        _uncertainty_html(evidence.get("uncertainty") or [],
                          evidence.get("final_assessment") or ""),
    ]
    return "".join(p for p in parts if p)


def _exec_summary_html(es: dict) -> str:
    findings = "".join(f"<li>{_e(x)}</li>" for x in es.get("key_findings") or [])
    agrees = "".join(f"<li>{_e(x)}</li>" for x in es.get("agreements") or [])
    disagrees = "".join(f"<li>{_e(x)}</li>" for x in es.get("disagreements") or [])
    plain = _e(es.get("plain_topic") or "")
    conclusion = _e(es.get("conclusion") or "")
    return (
        '<section class="ev ev-summary"><h2>Executive summary</h2>'
        f'<p class="ev-plain">{plain}</p>'
        f'<h3>Key findings</h3><ul>{findings}</ul>'
        f'<div class="ev-ad"><div><h3>Agreements</h3><ul>{agrees}</ul></div>'
        f'<div><h3>Disagreements</h3><ul>{disagrees}</ul></div></div>'
        f'<p class="ev-conclusion">{conclusion}</p></section>'
    )


def _consensus_html(cc: dict) -> str:
    cols = [
        ("Praise", cc.get("top_praise") or [], _LIME),
        ("Criticism", cc.get("top_criticism") or [], _MAGENTA),
        ("Misconceptions", cc.get("misconceptions") or [], _AMBER),
        ("Uncertainties", cc.get("uncertainties") or [], _SLATE),
    ]
    cards = "".join(
        f'<div class="ev-col" style="border-top:3px solid {color}">'
        f'<h3 style="color:{color}">{_e(title)}</h3><ul>'
        + "".join(f"<li>{_e(x)}</li>" for x in items) + "</ul></div>"
        for title, items, color in cols
    )
    return (
        '<section class="ev ev-consensus"><h2>Community consensus</h2>'
        f'<div class="ev-cols">{cards}</div></section>'
    )


def _claims_html(claims: list[dict]) -> str:
    radar = _strength_radar(claims)
    chart = _confidence_chart(claims)
    cards = "".join(_claim_card(c) for c in claims)
    return (
        '<section class="ev ev-claims"><h2>Evidence claims</h2>'
        f'<div class="ev-charts">{radar}{chart}</div>'
        f'<div class="ev-cards">{cards}</div></section>'
    )


def _procon_html(screen_a: list[dict], screen_b: list[dict]) -> str:
    donut = _procon_donut(screen_a, screen_b)
    pro = "".join(_claim_card(c) for c in screen_a)
    con = "".join(_claim_card(c) for c in screen_b)
    return (
        '<section class="ev ev-procon"><h2>Pro vs Con</h2>'
        f'<div class="ev-charts">{donut}</div>'
        f'<div class="ev-screens"><div class="ev-screen"><h3 style="color:{_LIME}">Pro</h3>{pro}</div>'
        f'<div class="ev-screen"><h3 style="color:{_MAGENTA}">Con</h3>{con}</div></div></section>'
    )


def _uncertainty_html(uncertainty: list[str], assessment: str) -> str:
    items = "".join(f"<li>{_e(x)}</li>" for x in uncertainty)
    unc = (
        '<section class="ev ev-uncertainty"><h2>Uncertainties</h2>'
        f'<ul>{items}</ul></section>' if items else
        '<section class="ev ev-uncertainty"><h2>Uncertainties</h2></section>'
    )
    asmt = (
        '<section class="ev ev-assessment"><h2>Final assessment</h2>'
        f'<p>{_e(assessment)}</p></section>' if assessment else ""
    )
    return unc + asmt


def _claim_card(claim: dict) -> str:
    side = str(claim.get("side") or "neutral")
    strength = str(claim.get("evidence_strength") or "weak")
    conf = _clamp(claim.get("confidence", 0.0))
    badge_color = _SIDE_COLOR.get(side, _SLATE)
    pill_color = _STRENGTH_COLOR.get(strength, _SLATE)
    ranking = claim.get("ranking") or {}
    bars = "".join(
        f'<div class="ev-mini"><span class="ev-mini-label">{_e(_AXIS_LABEL[ax])}</span>'
        f'<span class="ev-mini-track"><span class="ev-mini-fill" '
        f'style="width:{_clamp(ranking.get(ax, 0.0)) * 100:.1f}%;background:{_CYAN}"></span></span></div>'
        for ax in AXES
    )
    tags = "".join(
        f'<span class="ev-tag">{_e(t)}</span>'
        for t in claim.get("source_categories") or []
    )
    return (
        '<article class="ev-claim">'
        f'<div class="ev-claim-head"><span class="ev-badge" style="color:{badge_color}">{_e(side.upper())}</span>'
        f'<span class="ev-pill" style="color:{pill_color}">{_e(strength)}</span>'
        f'<span class="ev-conf">conf {conf:.2f}</span></div>'
        f'<p class="ev-claim-text">{_e(claim.get("text") or "")}</p>'
        f'<div class="ev-minis">{bars}</div>'
        f'<p class="ev-reason">{_e(claim.get("reasoning") or "")}</p>'
        f'<div class="ev-tags">{tags}</div></article>'
    )


def _confidence_chart(claims: list[dict]) -> str:
    width = 360
    row_h = 22
    bar_x = 150
    bar_w = 180
    n = len(claims)
    height = max(40, 14 + row_h * n)
    parts = [
        f'<svg class="ev-confidence" viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Claim confidence">',
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="10" fill="{_PANEL2}" />',
    ]
    for i, c in enumerate(claims):
        y = 10 + i * row_h
        conf = _clamp(c.get("confidence", 0.0))
        label = str(c.get("text") or "")[:20]
        parts.extend([
            f'<text x="10" y="{y + 11}" font-size="9" fill="{_TEXT}">{_e(label)}</text>',
            f'<rect x="{bar_x}" y="{y}" width="{bar_w}" height="13" rx="6.5" fill="{_TRACK}" />',
            f'<rect data-claim-bar x="{bar_x}" y="{y}" width="{bar_w * conf:.1f}" '
            f'height="13" rx="6.5" fill="{_CYAN}" />',
            f'<text x="{bar_x + bar_w + 6}" y="{y + 11}" font-size="9" '
            f'fill="{_MUTED}">{conf:.2f}</text>',
        ])
    parts.append("</svg>")
    return "\n".join(parts)


def _procon_donut(screen_a: list[dict], screen_b: list[dict]) -> str:
    width = height = 180
    cx, cy = width / 2, height / 2
    r = 60
    pro = len(screen_a)
    con = len(screen_b)
    total = pro + con
    circ = 2 * math.pi * r
    pro_frac = (pro / total) if total else 0.0
    pro_len = circ * pro_frac
    parts = [
        f'<svg class="ev-donut" viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Pro vs con claims">',
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="10" fill="{_PANEL2}" />',
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{_MAGENTA}" '
        'stroke-width="22" />',
    ]
    if total:
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{_LIME}" '
            f'stroke-width="22" stroke-dasharray="{pro_len:.2f} {circ - pro_len:.2f}" '
            f'transform="rotate(-90 {cx} {cy})" />'
        )
    parts.extend([
        f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" font-size="13" '
        f'font-weight="700" fill="{_TEXT}">{pro} / {con}</text>',
        f'<text x="{cx}" y="{cy + 14}" text-anchor="middle" font-size="9" '
        f'fill="{_MUTED}">pro / con</text>',
        "</svg>",
    ])
    return "\n".join(parts)


def _strength_radar(claims: list[dict]) -> str:
    width = height = 220
    cx, cy = width / 2, height / 2
    r = 80
    ranked = [c.get("ranking") for c in claims if c.get("ranking")]
    means = []
    for ax in AXES:
        vals = [_clamp((rk or {}).get(ax, 0.0)) for rk in ranked]
        means.append(sum(vals) / len(vals) if vals else 0.0)

    n = len(AXES)
    def point(frac: float, i: int) -> tuple[float, float]:
        angle = -math.pi / 2 + 2 * math.pi * i / n
        return cx + r * frac * math.cos(angle), cy + r * frac * math.sin(angle)

    grid = []
    for ring in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (point(ring, i) for i in range(n)))
        grid.append(f'<polygon points="{pts}" fill="none" stroke="{_BORDER}" stroke-width="1" />')
    spokes = "".join(
        f'<line x1="{cx}" y1="{cy}" x2="{point(1.0, i)[0]:.1f}" '
        f'y2="{point(1.0, i)[1]:.1f}" stroke="{_BORDER}" stroke-width="1" />'
        for i in range(n)
    )
    labels = "".join(
        f'<text x="{point(1.18, i)[0]:.1f}" y="{point(1.18, i)[1]:.1f}" '
        f'text-anchor="middle" font-size="8" fill="{_MUTED}">{_e(_AXIS_LABEL[AXES[i]])}</text>'
        for i in range(n)
    )
    shape = ""
    if any(m > 0 for m in means):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (point(means[i], i) for i in range(n)))
        shape = (
            f'<polygon points="{pts}" fill="{_CYAN}" fill-opacity="0.25" '
            f'stroke="{_CYAN}" stroke-width="2" />'
        )
    return (
        f'<svg class="ev-radar" viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Mean evidence strength radar">'
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="10" fill="{_PANEL2}" />'
        + "".join(grid) + spokes + shape + labels + "</svg>"
    )


def _clamp(v) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def _e(value) -> str:
    return html.escape(str(value), quote=False)


def _a(value) -> str:
    return html.escape(str(value), quote=True)
