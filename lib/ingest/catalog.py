"""Cataloging + normalization for processed documents.

Centralizes the normalization rules scattered across connectors (author
prefixes, URL tracking params, whitespace) and assigns content-stable IDs so
the same post fetched twice maps to one catalog entry. `Catalog` is an
in-memory index with id/source lookup and content dedup.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_WS = re.compile(r"\s+")
_AUTHOR_PREFIX = re.compile(r"^(/?u/|@)+", re.IGNORECASE)
_DROP_QUERY_PREFIXES = ("utm_", "fbclid", "gclid", "ref", "ref_src", "mc_")


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return _WS.sub(" ", text).strip()


def normalize_author(author: str | None) -> str:
    if not author:
        return ""
    return _AUTHOR_PREFIX.sub("", author.strip()).lower()


def normalize_url(url: str | None) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    if not parts.scheme and not parts.netloc:
        return url.strip()
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_DROP_QUERY_PREFIXES)
    ]
    path = parts.path.rstrip("/")
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        path,
        urlencode(query),
        "",
    ))


def stable_id(source: str, text: str) -> str:
    """Deterministic content hash, insensitive to case/whitespace."""
    key = f"{source.strip().lower()}\x00{normalize_text(text).lower()}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"cat:{digest}"


class Catalog:
    """In-memory index of normalized documents keyed by stable content id."""

    def __init__(self) -> None:
        self._by_id: dict[str, dict[str, Any]] = {}

    def add(self, doc: dict[str, Any]) -> str:
        cid = stable_id(doc.get("source", ""), doc.get("text", ""))
        if cid in self._by_id:
            return cid
        entry = dict(doc)
        entry["catalog_id"] = cid
        entry["author"] = normalize_author(doc.get("author"))
        entry["url"] = normalize_url(doc.get("url"))
        self._by_id[cid] = entry
        return cid

    def get(self, catalog_id: str) -> dict[str, Any] | None:
        return self._by_id.get(catalog_id)

    def by_source(self, source: str) -> list[dict[str, Any]]:
        return [e for e in self._by_id.values() if e.get("source") == source]

    def all(self) -> list[dict[str, Any]]:
        return list(self._by_id.values())

    def __contains__(self, catalog_id: str) -> bool:
        return catalog_id in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)
