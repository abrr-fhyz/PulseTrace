"""Hacker News connector via Algolia search API (no auth)."""
from __future__ import annotations
import requests
from .base import Connector, Post


class HNConnector(Connector):
    name = "hn"
    URL = "https://hn.algolia.com/api/v1/search"

    def fetch(self, query: str, limit: int = 50) -> list[Post]:
        r = requests.get(
            self.URL,
            params={"query": query, "hitsPerPage": limit},
            timeout=15,
        )
        r.raise_for_status()
        out: list[Post] = []
        for h in r.json().get("hits", []):
            text = ((h.get("title") or "") + "\n\n"
                    + (h.get("story_text") or h.get("comment_text") or "")).strip()
            if not text:
                continue
            obj_id = h.get("objectID")
            out.append(Post(
                id=f"hn:{obj_id}",
                source="hn",
                text=text,
                author=h.get("author"),
                url=h.get("url") or f"https://news.ycombinator.com/item?id={obj_id}",
                ts=int(h.get("created_at_i") or 0),
                reactions=int(h.get("points") or 0),
                comments=int(h.get("num_comments") or 0),
                shares=0,
                raw={"tags": h.get("_tags", [])},
            ))
        return out
