from __future__ import annotations

import pandas as pd

from lib.ingest.tabular import COLUMNS, clean_frame, normalize_posts, posts_to_frame


def _p(**over):
    base = {"id": "a", "source": "reddit", "text": "hi"}
    base.update(over)
    return base


def test_posts_to_frame_has_consistent_columns():
    df = posts_to_frame([{"id": "a", "source": "reddit", "text": "hi"}])
    assert list(df.columns) == list(COLUMNS)


def test_missing_keys_filled_with_defaults():
    df = posts_to_frame([{"id": "a", "source": "reddit", "text": "hi"}])
    row = df.iloc[0]
    assert row["reactions"] == 0
    assert row["author"] == ""
    assert row["ts"] == 0


def test_numeric_coercion_from_strings():
    df = posts_to_frame([_p(reactions="12", comments="bad", ts="1700000000")])
    row = df.iloc[0]
    assert row["reactions"] == 12
    assert row["comments"] == 0  # non-numeric coerced to 0
    assert row["ts"] == 1700000000
    assert df["reactions"].dtype.kind == "i"


def test_empty_list_returns_empty_typed_frame():
    df = posts_to_frame([])
    assert list(df.columns) == list(COLUMNS)
    assert len(df) == 0


def test_clean_frame_dedupes_by_id_keep_first():
    df = posts_to_frame([_p(id="dup", text="first"), _p(id="dup", text="second")])
    out = clean_frame(df)
    assert len(out) == 1
    assert out.iloc[0]["text"] == "first"


def test_clean_frame_drops_rows_missing_id_or_text():
    df = posts_to_frame([_p(id="", text="x"), _p(id="b", text=""), _p(id="c", text="ok")])
    out = clean_frame(df)
    assert list(out["id"]) == ["c"]


def test_clean_frame_fills_null_strings():
    raw = pd.DataFrame([{"id": "a", "source": "reddit", "text": "hi", "author": None}])
    df = posts_to_frame(raw.to_dict("records"))
    out = clean_frame(df)
    assert out.iloc[0]["author"] == ""


def test_normalize_posts_end_to_end():
    posts = [
        _p(id="a", text="one", reactions="5"),
        _p(id="a", text="dupe"),
        _p(id="b", text=""),
        _p(id="c", text="three"),
    ]
    out = normalize_posts(posts)
    assert list(out["id"]) == ["a", "c"]
    assert out.iloc[0]["reactions"] == 5


def test_large_dataset_dedupes():
    posts = [_p(id=str(i % 100), text=f"t{i}") for i in range(5000)]
    out = normalize_posts(posts)
    assert len(out) == 100
