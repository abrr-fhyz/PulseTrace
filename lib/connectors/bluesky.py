"""Bluesky connector via the AT Protocol searchPosts endpoint.

Requires an app password (preferred over a main password; revocable, scoped).
Credentials come from env:
  BLUESKY_APP_USERNAME / BLUESKY_APP_PASSWORD   (this project's names)
  BSKY_HANDLE / BSKY_APP_PASSWORD               (also accepted)

A session JWT is created once and cached with a short TTL. Returns [] on any
failure (missing creds, Cloudflare block, expired token) so the agent loop
tolerates absence.
"""
from __future__ import annotations
import os
import time
from urllib.parse import urlencode

import requests

from .base import Connector, Post

SESSION_URL = "https://bsky.social/xrpc/com.atproto.server.createSession"
SEARCH_URL = "https://bsky.social/xrpc/app.bsky.feed.searchPosts"
_TOKEN_TTL = 90 * 60

_cached_token: str | None = None
_token_at: float = 0.0


def _creds() -> tuple[str, str]:
    handle = (os.environ.get("BLUESKY_APP_USERNAME")
              or os.environ.get("BSKY_HANDLE") or "")
    pw = (os.environ.get("BLUESKY_APP_PASSWORD")
          or os.environ.get("BSKY_APP_PASSWORD") or "")
    return handle, pw


def _token() -> str | None:
    global _cached_token, _token_at
    if _cached_token and (time.monotonic() - _token_at < _TOKEN_TTL):
        return _cached_token
    handle, pw = _creds()
    if not (handle and pw):
        return None
    try:
        r = requests.post(SESSION_URL,
                          json={"identifier": handle, "password": pw}, timeout=15)
        r.raise_for_status()
        tok = r.json().get("accessJwt")
    except (requests.RequestException, ValueError):
        return None
    if tok:
        _cached_token = tok
        _token_at = time.monotonic()
    return tok


def _iso_to_epoch(value: str | None) -> int:
    if not value:
        return int(time.time())
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return int(time.time())


def _parse(posts: list[dict]) -> list[Post]:
    out: list[Post] = []
    for p in posts:
        record = p.get("record") or {}
        text = (record.get("text") or "").strip()
        if not text:
            continue
        author = p.get("author") or {}
        handle = author.get("handle") or ""
        uri = p.get("uri") or ""
        rkey = uri.rsplit("/", 1)[-1] if uri else ""
        url = (f"https://bsky.app/profile/{handle}/post/{rkey}"
               if handle and rkey else "")
        out.append(Post(
            id=f"bluesky:{uri or text[:32]}",
            source="bluesky",
            text=text[:2000],
            author=handle or None,
            url=url,
            ts=_iso_to_epoch(p.get("indexedAt") or record.get("createdAt")),
            reactions=int(p.get("likeCount") or 0),
            comments=int(p.get("replyCount") or 0),
            shares=int(p.get("repostCount") or 0),
            raw={"quotes": int(p.get("quoteCount") or 0)},
        ))
    return out


class BlueskyConnector(Connector):
    name = "bluesky"

    def fetch(self, query: str, limit: int = 30) -> list[Post]:
        tok = _token()
        if not tok:
            return []
        params = {"q": query, "limit": str(min(limit, 100)), "sort": "top"}
        try:
            r = requests.get(f"{SEARCH_URL}?{urlencode(params)}",
                             headers={"Authorization": f"Bearer {tok}"}, timeout=20)
            r.raise_for_status()
            posts = r.json().get("posts", [])
        except (requests.RequestException, ValueError):
            return []
        return _parse(posts)[:limit]
