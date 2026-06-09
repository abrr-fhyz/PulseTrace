"""Post-record schema validation for the MCP schema-report tool.

Mirrors the fields of `lib.connectors.base.Post`. `validate_posts` computes a
real pass rate and per-field failure tally over a run's posts.json — no mocks.
"""
from __future__ import annotations
from dataclasses import dataclass

# field -> (accepted python types, required?)
_FIELDS: dict[str, tuple[tuple[type, ...], bool]] = {
    "id": ((str,), True),
    "source": ((str,), True),
    "text": ((str,), True),
    "ts": ((int,), True),
    "reactions": ((int,), True),
    "comments": ((int,), True),
    "shares": ((int,), True),
    "author": ((str, type(None)), False),
    "url": ((str, type(None)), False),
    "raw": ((dict,), False),
}


@dataclass
class FieldError:
    field: str
    kind: str  # "missing" | "wrong_type" | "empty"


def validate_post(post: dict) -> list[FieldError]:
    errors: list[FieldError] = []
    for field, (types, required) in _FIELDS.items():
        if field not in post:
            if required:
                errors.append(FieldError(field, "missing"))
            continue
        value = post[field]
        if not isinstance(value, types) or isinstance(value, bool):
            errors.append(FieldError(field, "wrong_type"))
            continue
        if required and isinstance(value, str) and not value.strip():
            errors.append(FieldError(field, "empty"))
    return errors


def validate_posts(posts: list[dict]) -> dict:
    total = len(posts)
    failed_fields: dict[str, int] = {}
    error_kinds: set[str] = set()
    bad_records = 0
    for post in posts:
        errs = validate_post(post)
        if errs:
            bad_records += 1
        for e in errs:
            failed_fields[e.field] = failed_fields.get(e.field, 0) + 1
            error_kinds.add(e.kind)
    passed = total - bad_records
    pass_rate = round(100.0 * passed / total, 2) if total else 100.0
    return {
        "total_records": total,
        "passed_records": passed,
        "failed_records": bad_records,
        "pass_rate": pass_rate,
        "failed_fields": failed_fields,
        "error_types": sorted(error_kinds),
    }
