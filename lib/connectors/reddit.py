"""Reddit connector. PRAW when app creds exist, keyless RSS fallback otherwise.

PRAW (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET) gives scores, comment counts,
and selftext. Without creds we fall back to the public `search.rss` Atom feed —
no auth, but engagement counts come back zero. The fallback keeps Reddit
available out of the box. Returns [] on any failure.
"""
from __future__ import annotations
import os
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import requests

from .base import Connector, Post

_ATOM = "{http://www.w3.org/2005/Atom}"
_RSS_URL = "https://www.reddit.com/search.rss?q={q}&sort=relevance&t=month"
_RSS_HEADERS = {"User-Agent": os.environ.get("REDDIT_USER_AGENT", "pulsetrace/0.2")}


def _iso_to_epoch(value: str | None) -> int:
    if not value:
        return int(time.time())
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return int(time.time())


def _subreddit_from_url(url: str) -> str:
    m = re.search(r"/r/([^/]+)/", url)
    return m.group(1) if m else ""


def _parse_feed(xml_text: str) -> list[Post]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out: list[Post] = []
    for entry in root.iter(f"{_ATOM}entry"):
        link_el = entry.find(f"{_ATOM}link")
        url = link_el.get("href", "").strip() if link_el is not None else ""
        if not url or "/comments/" not in url:
            continue
        title_el = entry.find(f"{_ATOM}title")
        title = (title_el.text or "").strip() if title_el is not None else ""
        content_el = entry.find(f"{_ATOM}content")
        body = ""
        if content_el is not None and content_el.text:
            body = re.sub(r"<[^>]+>", " ", content_el.text)
            body = re.sub(r"\s+", " ", body).strip()[:500]
        text = (title + ("\n\n" + body if body else "")).strip()
        if not text:
            continue
        author = ""
        author_el = entry.find(f"{_ATOM}author/{_ATOM}name")
        if author_el is not None and author_el.text:
            author = author_el.text.strip().removeprefix("/u/").removeprefix("u/")
        updated_el = entry.find(f"{_ATOM}updated")
        updated = (updated_el.text or "").strip() if updated_el is not None else ""
        out.append(Post(
            id=f"reddit:{url.rstrip('/').rsplit('/comments/', 1)[-1][:24]}",
            source="reddit",
            text=text,
            author=author or None,
            url=url,
            ts=_iso_to_epoch(updated),
            reactions=0,
            comments=0,
            shares=0,
            raw={"subreddit": _subreddit_from_url(url), "via": "rss"},
        ))
    return out


class RedditConnector(Connector):
    name = "reddit"

    def __init__(self) -> None:
        self._praw = None
        if os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET"):
            try:
                import praw
                self._praw = praw.Reddit(
                    client_id=os.environ["REDDIT_CLIENT_ID"],
                    client_secret=os.environ["REDDIT_CLIENT_SECRET"],
                    user_agent=os.environ.get("REDDIT_USER_AGENT", "pulsetrace/0.2"),
                )
                self._praw.read_only = True
            except Exception:
                self._praw = None

    def fetch(self, query: str, limit: int = 50) -> list[Post]:
        if self._praw is not None:
            try:
                return self._fetch_praw(query, limit)
            except Exception:
                pass
        return self._fetch_rss(query, limit)

    def _fetch_praw(self, query: str, limit: int) -> list[Post]:
        out: list[Post] = []
        for sub in self._praw.subreddit("all").search(query, limit=limit, sort="relevance"):
            text = (getattr(sub, "title", "") + "\n\n" + (getattr(sub, "selftext", "") or "")).strip()
            if not text:
                continue
            out.append(Post(
                id=f"reddit:{sub.id}",
                source="reddit",
                text=text,
                author=str(sub.author) if sub.author else None,
                url=f"https://reddit.com{sub.permalink}",
                ts=int(getattr(sub, "created_utc", 0) or time.time()),
                reactions=int(getattr(sub, "score", 0) or 0),
                comments=int(getattr(sub, "num_comments", 0) or 0),
                shares=0,
                raw={"subreddit": str(sub.subreddit), "via": "praw"},
            ))
        return out

    def _fetch_rss(self, query: str, limit: int) -> list[Post]:
        try:
            r = requests.get(
                _RSS_URL.format(q=quote_plus(query)),
                headers=_RSS_HEADERS, timeout=15,
            )
            r.raise_for_status()
        except requests.RequestException:
            return []
        return _parse_feed(r.text)[:limit]
