from __future__ import annotations

import pytest

from lib.ingest.schemas import (
    SchemaValidationError,
    assert_valid,
    get_schema,
    list_versions,
    validate_document,
)


def _doc(**over):
    base = {"id": "reddit:a", "source": "reddit", "text": "hello"}
    base.update(over)
    return base


def test_valid_post_has_no_errors():
    assert validate_document(_doc(), "post") == []


def test_missing_required_field_reported():
    errs = validate_document({"id": "a", "source": "reddit"}, "post")
    assert any("text" in e for e in errs)


def test_wrong_type_reported():
    errs = validate_document(_doc(reactions="lots"), "post")
    assert any("reactions" in e for e in errs)


def test_negative_int_reported():
    errs = validate_document(_doc(ts=-5), "post")
    assert any("ts" in e for e in errs)


def test_multiple_errors_all_reported():
    errs = validate_document({"id": "", "reactions": -1}, "post")
    assert len(errs) >= 2


def test_extra_fields_allowed():
    assert validate_document(_doc(raw={"x": 1}, extra="ok"), "post") == []


def test_run_document_schema():
    run = {"run_id": "1700-abc", "query": "topic", "created": 1700000000}
    assert validate_document(run, "run") == []
    bad = validate_document({"query": "topic"}, "run")
    assert any("run_id" in e for e in bad)


def test_get_schema_returns_latest_with_version():
    schema = get_schema("post")
    assert schema["version"] == "1.0"


def test_get_schema_by_explicit_version():
    assert get_schema("post", "1.0")["version"] == "1.0"


def test_unknown_version_raises():
    with pytest.raises(KeyError):
        get_schema("post", "9.9")


def test_unknown_schema_name_raises():
    with pytest.raises(KeyError):
        validate_document(_doc(), "nope")


def test_list_versions():
    assert "1.0" in list_versions("post")


def test_assert_valid_raises_with_detail():
    with pytest.raises(SchemaValidationError) as ei:
        assert_valid({"id": "a"}, "post")
    assert "text" in str(ei.value)


def test_assert_valid_passes_silently():
    assert_valid(_doc(), "post") is None
