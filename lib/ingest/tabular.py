"""Pandas tabular layer for post collections.

Turns lists of post dicts into a consistently-typed DataFrame for bulk
cleaning: column normalization, numeric coercion, null handling, dedup by id.
Vectorized throughout so it stays cheap on large (MAX_POSTS-scale and beyond)
batches.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

COLUMNS = (
    "id", "source", "text", "author", "url",
    "ts", "reactions", "comments", "shares",
)
_STR_COLS = ("id", "source", "text", "author", "url")
_INT_COLS = ("ts", "reactions", "comments", "shares")


def posts_to_frame(posts: list[dict[str, Any]]) -> pd.DataFrame:
    """Build a DataFrame with the canonical columns and coerced dtypes."""
    df = pd.DataFrame(list(posts), columns=list(COLUMNS))
    for col in _STR_COLS:
        df[col] = df[col].fillna("").astype(str).str.strip()
    for col in _INT_COLS:
        df[col] = (
            pd.to_numeric(df[col], errors="coerce")
            .fillna(0)
            .astype("int64")
        )
    return df


def dedupe(df: pd.DataFrame, subset: str = "id") -> pd.DataFrame:
    return df.drop_duplicates(subset=subset, keep="first").reset_index(drop=True)


def drop_empty(df: pd.DataFrame) -> pd.DataFrame:
    mask = (df["id"] != "") & (df["text"] != "")
    return df[mask].reset_index(drop=True)


def clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Drop empty/duplicate rows; assumes coerced dtypes from posts_to_frame."""
    return dedupe(drop_empty(df))


def normalize_posts(posts: list[dict[str, Any]]) -> pd.DataFrame:
    """Full pipeline: records -> typed -> cleaned DataFrame."""
    return clean_frame(posts_to_frame(posts))
