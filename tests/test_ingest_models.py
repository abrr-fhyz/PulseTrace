from __future__ import annotations

import pytest
from pydantic import ValidationError

from lib.ingest.models import (
    EnrichedPost,
    PostModel,
    validate_post,
    validate_posts,
)


def _post(**over):
    base = {"id": "reddit:abc", "source": "reddit", "text": "hello world"}
    base.update(over)
    return base


def test_valid_post_parses_with_defaults():
    p = PostModel(**_post())
    assert p.id == "reddit:abc"
    assert p.ts == 0
    assert p.reactions == 0
    assert p.raw == {}
    assert p.author is None


def test_text_is_stripped():
    p = PostModel(**_post(text="  spaced  "))
    assert p.text == "spaced"


def test_empty_text_rejected():
    with pytest.raises(ValidationError):
        PostModel(**_post(text="   "))


def test_missing_required_field_rejected():
    with pytest.raises(ValidationError):
        PostModel(id="x", source="reddit")  # no text


def test_negative_engagement_rejected():
    with pytest.raises(ValidationError):
        PostModel(**_post(reactions=-1))


def test_non_http_url_rejected():
    with pytest.raises(ValidationError):
        PostModel(**_post(url="javascript:alert(1)"))


def test_http_url_accepted():
    p = PostModel(**_post(url="https://reddit.com/r/x/comments/1"))
    assert str(p.url).startswith("https://")


def test_validate_post_returns_model():
    p = validate_post(_post())
    assert isinstance(p, PostModel)


def test_validate_posts_splits_valid_and_errors():
    rows = [_post(), _post(text=""), _post(id="ok2")]
    valid, errors = validate_posts(rows)
    assert len(valid) == 2
    assert len(errors) == 1
    # actionable diagnostics: index + field + message
    idx, diag = errors[0]
    assert idx == 1
    assert "text" in diag


def test_enriched_post_extends_with_optional_fields():
    e = EnrichedPost(**_post(), cluster_id=3, sentiment="positive", score=0.8)
    assert e.cluster_id == 3
    assert e.sentiment == "positive"
    assert e.score == 0.8


def test_enriched_post_rejects_bad_sentiment():
    with pytest.raises(ValidationError):
        EnrichedPost(**_post(), sentiment="ecstatic")


def test_enriched_post_score_out_of_range_rejected():
    with pytest.raises(ValidationError):
        EnrichedPost(**_post(), score=2.0)
