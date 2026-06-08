"""Pydantic models for ingestion entities.

PostModel is the validated mirror of `lib.connectors.base.Post`. Validate
right after extraction (`validate_post`/`validate_posts`) and again after
enrichment via `EnrichedPost`. Errors are surfaced as (index, diagnostic)
pairs so callers can log/skip bad rows without aborting the run.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SENTIMENTS = ("positive", "neutral", "negative", "mixed")


class PostModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    text: str = Field(min_length=1)
    author: str | None = None
    url: str | None = None
    ts: int = Field(default=0, ge=0)
    reactions: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def _url_is_http(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must be http(s)")
        return v


class EnrichedPost(PostModel):
    """PostModel plus fields added by the agent pipeline."""

    cluster_id: int | None = None
    sentiment: Literal["positive", "neutral", "negative", "mixed"] | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)


def validate_post(data: dict[str, Any]) -> PostModel:
    """Validate one record; raises pydantic ValidationError on failure."""
    return PostModel(**data)


def _diagnostic(err: ValidationError) -> str:
    parts = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "<root>"
        parts.append(f"{loc}: {e['msg']}")
    return "; ".join(parts)


def validate_posts(
    rows: list[dict[str, Any]],
) -> tuple[list[PostModel], list[tuple[int, str]]]:
    """Split rows into validated models and (index, diagnostic) errors."""
    valid: list[PostModel] = []
    errors: list[tuple[int, str]] = []
    for i, row in enumerate(rows):
        try:
            valid.append(PostModel(**row))
        except ValidationError as e:
            errors.append((i, _diagnostic(e)))
    return valid, errors
