from __future__ import annotations
from lib import briefing_evidence as be

def _claim(side="pro", conf=0.7, strength="strong"):
    return {"text": "Battery lasts all day", "side": side, "confidence": conf,
            "evidence_strength": strength, "reasoning": "multiple corroborating posts",
            "source_categories": ["forums", "social"], "cluster_ids": [1],
            "ranking": {"credibility": 0.8, "data_quality": 0.6, "sample_size": 0.5,
                        "recency": 0.7, "corroboration": 0.66}}

def test_render_empty_returns_blank():
    assert be.render_top({}) == ""
    assert be.render_bottom({}) == ""

def test_render_neutral_opinion_none_blank():
    ev = {"opinion": None, "exec_summary": {"plain_topic": "x", "key_findings": ["a"],
          "agreements": [], "disagreements": [], "conclusion": "c"}, "topic_overview": "o"}
    assert be.render_top(ev) == ""

def test_render_top_with_opinion_has_markers():
    ev = {"opinion": "phone is great",
          "exec_summary": {"plain_topic": "Phone reviews", "key_findings": ["good battery"],
                           "agreements": ["fast"], "disagreements": ["pricey"],
                           "conclusion": "solid mid-range"},
          "topic_overview": "Discussion centers on value."}
    out = be.render_top(ev)
    assert "Executive" in out and "good battery" in out
    assert "Discussion centers on value." in out

def test_render_bottom_has_sections_and_charts():
    ev = {"opinion": "phone is great",
          "community_consensus": {"top_praise": ["battery"], "top_criticism": ["price"],
                                  "misconceptions": ["overheats"], "uncertainties": ["longevity"]},
          "claims": [_claim("pro"), _claim("con", 0.4, "weak")],
          "screen_a": [_claim("pro")], "screen_b": [_claim("con", 0.4, "weak")],
          "uncertainty": ["sample skew"], "final_assessment": "Mostly supports the view."}
    out = be.render_bottom(ev)
    for marker in ("Community", "battery", "price", "Pro", "Con",
                   "Uncertaint", "Mostly supports", "<svg"):
        assert marker in out

def test_charts_handle_empty():
    assert "<svg" in be._confidence_chart([])
    assert "<svg" in be._procon_donut([], [])
    assert "<svg" in be._strength_radar([])

def test_confidence_chart_one_bar_per_claim():
    svg = be._confidence_chart([_claim(), _claim("con")])
    assert svg.count("data-claim-bar") == 2
