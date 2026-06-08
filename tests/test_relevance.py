"""TDD spec for lib/relevance.py — query-centric scoring + query cleanup."""
from lib.relevance import (
    token_overlap_relevance,
    extract_core_subject,
    extract_compound_terms,
)


def test_exact_phrase_scores_high():
    s = token_overlap_relevance("retrieval augmented generation",
                                "Retrieval augmented generation explained for beginners")
    assert s >= 0.8


def test_offtopic_scores_low():
    s = token_overlap_relevance("retrieval augmented generation",
                                "Roast my resume - SDE 2 looking for a job, 5 yoe")
    assert s < 0.2


def test_ontopic_beats_generic():
    on = token_overlap_relevance("openai codex pricing",
                                 "OpenAI Codex pricing tiers compared")
    generic = token_overlap_relevance("openai codex pricing",
                                      "best pricing thoughts and reviews of stuff")
    assert on > generic


def test_generic_only_match_capped_low():
    # only the low-signal word "pricing" overlaps; must stay below filter line
    s = token_overlap_relevance("openai codex pricing",
                                "general pricing discussion about groceries")
    assert s <= 0.3


def test_empty_query_is_neutral():
    assert token_overlap_relevance("", "anything here") == 0.5


def test_no_overlap_is_zero():
    assert token_overlap_relevance("kubernetes", "I love baking sourdough bread") == 0.0


def test_extract_core_subject_strips_prefix_and_noise():
    assert extract_core_subject("what are the best noise cancelling headphones 2026") \
        == "noise cancelling headphones 2026"


def test_extract_core_subject_strips_how_to():
    assert extract_core_subject("how to set up a GLP-1 supplement routine") \
        == "glp-1 supplement routine"


def test_extract_core_subject_keeps_entity_when_all_noise():
    # all-noise input must not collapse to empty
    out = extract_core_subject("best latest tips")
    assert out


def test_extract_compound_terms_hyphen_and_titlecase():
    terms = extract_compound_terms("Claude Code with multi-agent setup")
    assert "multi-agent" in terms
    assert "Claude Code" in terms
