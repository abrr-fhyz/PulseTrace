"""Polymarket connector via the public Gamma search API (no auth).

Each active event becomes one Post; text = event title plus its top market
questions. Prediction-market odds are a useful sentiment signal: the crowd
prices a probability, which complements free-text opinion from other sources.
Returns [] on any failure so the agent loop tolerates absence.
"""
from __future__ import annotations
import time
from urllib.parse import urlencode

import requests

from .base import Connector, Post

SEARCH_URL = "https://gamma-api.polymarket.com/public-search"


def _market_lines(markets: list[dict]) -> list[str]:
    lines: list[str] = []
    for m in markets:
        if m.get("closed") or not m.get("active", True):
            continue
        q = (m.get("question") or "").strip()
        if q:
            lines.append(q)
    return lines


def _iso_to_epoch(value: str | None) -> int:
    if not value:
        return int(time.time())
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return int(time.time())


def _parse(events: list[dict]) -> list[Post]:
    out: list[Post] = []
    for ev in events:
        if ev.get("closed") or not ev.get("active", True):
            continue
        title = (ev.get("title") or "").strip()
        if not title:
            continue
        markets = ev.get("markets") or []
        body = "\n".join(_market_lines(markets)[:8])
        text = (title + ("\n\n" + body if body else "")).strip()
        slug = ev.get("slug") or ""
        ev_id = str(ev.get("id") or "")
        url = (f"https://polymarket.com/event/{slug}" if slug
               else f"https://polymarket.com/event/{ev_id}")
        try:
            volume = int(float(ev.get("volume1mo") or ev.get("volume") or 0))
        except (ValueError, TypeError):
            volume = 0
        out.append(Post(
            id=f"polymarket:{ev_id}",
            source="polymarket",
            text=text[:2000],
            author=None,
            url=url,
            ts=_iso_to_epoch(ev.get("updatedAt")),
            reactions=volume,
            comments=len(markets),
            shares=0,
            raw={"slug": slug, "market_count": len(markets)},
        ))
    return out


class PolymarketConnector(Connector):
    name = "polymarket"

    def fetch(self, query: str, limit: int = 30) -> list[Post]:
        params = {
            "q": query,
            "page": "1",
            "events_status": "active",
            "keep_closed_markets": "0",
        }
        try:
            r = requests.get(f"{SEARCH_URL}?{urlencode(params)}", timeout=15)
            r.raise_for_status()
            events = r.json().get("events", [])
        except (requests.RequestException, ValueError):
            return []
        return _parse(events)[:limit]
