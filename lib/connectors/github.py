"""GitHub connector via the Issues/PRs search API.

Works unauthenticated (10 req/min, low cap) and uses GITHUB_TOKEN when present
(30 req/min, higher cap). Issues and PRs surface developer sentiment about
tools, libraries, and releases that rarely shows up on social platforms.
Returns [] on any failure so the agent loop tolerates absence.
"""
from __future__ import annotations
import os
from urllib.parse import urlencode

import requests

from .base import Connector, Post

SEARCH_URL = "https://api.github.com/search/issues"


def _repo_from_url(html_url: str) -> str:
    parts = html_url.replace("https://github.com/", "").split("/")
    return "/".join(parts[:2]) if len(parts) >= 2 else ""


def _iso_to_epoch(value: str | None) -> int:
    if not value:
        return 0
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return 0


def _parse(items: list[dict]) -> list[Post]:
    out: list[Post] = []
    for it in items:
        title = (it.get("title") or "").strip()
        body = (it.get("body") or "").strip()
        text = (title + ("\n\n" + body if body else "")).strip()
        if not text:
            continue
        reactions = 0
        if isinstance(it.get("reactions"), dict):
            reactions = int(it["reactions"].get("total_count") or 0)
        html_url = it.get("html_url") or ""
        author = ""
        if isinstance(it.get("user"), dict):
            author = it["user"].get("login") or ""
        out.append(Post(
            id=f"github:{it.get('id') or html_url}",
            source="github",
            text=text[:2000],
            author=author or None,
            url=html_url,
            ts=_iso_to_epoch(it.get("created_at")),
            reactions=reactions,
            comments=int(it.get("comments") or 0),
            shares=0,
            raw={
                "repo": _repo_from_url(html_url),
                "is_pr": "pull_request" in it,
                "state": it.get("state", ""),
            },
        ))
    return out


class GitHubConnector(Connector):
    name = "github"

    def fetch(self, query: str, limit: int = 30) -> list[Post]:
        params = {
            "q": query,
            "sort": "reactions",
            "order": "desc",
            "per_page": str(min(limit, 100)),
        }
        headers = {"Accept": "application/vnd.github+json"}
        token = os.environ.get("GITHUB_TOKEN", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            r = requests.get(f"{SEARCH_URL}?{urlencode(params)}",
                             headers=headers, timeout=20)
            r.raise_for_status()
            items = r.json().get("items", [])
        except (requests.RequestException, ValueError):
            return []
        return _parse(items)[:limit]
