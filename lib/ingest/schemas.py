"""Versioned JSON Schemas for persisted documents + validators.

`store.py` writes posts/clusters/run JSON with no guard. These schemas gate
documents before persistence. Schemas are versioned in a registry so the shape
can evolve without breaking old runs; `validate_document` reports every
violation with a JSON-path so rejects are debuggable.
"""
from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator

_DRAFT = "https://json-schema.org/draft/2020-12/schema"

_NONNEG_INT = {"type": "integer", "minimum": 0}

_POST_V1 = {
    "$schema": _DRAFT,
    "title": "post",
    "version": "1.0",
    "type": "object",
    "required": ["id", "source", "text"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "source": {"type": "string", "minLength": 1},
        "text": {"type": "string", "minLength": 1},
        "author": {"type": ["string", "null"]},
        "url": {"type": ["string", "null"]},
        "ts": _NONNEG_INT,
        "reactions": _NONNEG_INT,
        "comments": _NONNEG_INT,
        "shares": _NONNEG_INT,
        "raw": {"type": "object"},
    },
    "additionalProperties": True,
}

_RUN_V1 = {
    "$schema": _DRAFT,
    "title": "run",
    "version": "1.0",
    "type": "object",
    "required": ["run_id", "query", "created"],
    "properties": {
        "run_id": {"type": "string", "minLength": 1},
        "query": {"type": "string", "minLength": 1},
        "created": _NONNEG_INT,
        "n_posts": _NONNEG_INT,
        "n_clusters": _NONNEG_INT,
    },
    "additionalProperties": True,
}

REGISTRY: dict[str, dict[str, dict[str, Any]]] = {
    "post": {"1.0": _POST_V1},
    "run": {"1.0": _RUN_V1},
}


class SchemaValidationError(ValueError):
    """Raised by assert_valid when a document violates its schema."""


def list_versions(name: str) -> list[str]:
    return sorted(REGISTRY[name].keys())


def get_schema(name: str, version: str | None = None) -> dict[str, Any]:
    """Return a schema; latest version when `version` is None."""
    versions = REGISTRY[name]
    if version is None:
        version = max(versions)
    return versions[version]


def validate_document(
    doc: dict[str, Any], name: str, version: str | None = None
) -> list[str]:
    """Return a list of human-readable violations (empty == valid)."""
    schema = get_schema(name, version)
    validator = Draft202012Validator(schema)
    out: list[str] = []
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
        path = "/".join(str(p) for p in err.path) or "<root>"
        out.append(f"{path}: {err.message}")
    return out


def assert_valid(
    doc: dict[str, Any], name: str, version: str | None = None
) -> None:
    """Raise SchemaValidationError listing all violations, else return None."""
    errors = validate_document(doc, name, version)
    if errors:
        raise SchemaValidationError(
            f"{name} document invalid: " + "; ".join(errors)
        )
    return None
