"""Twitter / X connector via twikit (unofficial guest/cookie auth).

WARNING: X aggressively rate-limits and bans automation.
 - twikit uses unofficial endpoints; X can break them at any time.
 - Two auth modes:
     1. Cookie file at `info/x_cookies.json` (preferred; export from logged-in browser).
     2. Username/password from env (`X_USERNAME`, `X_PASSWORD`, `X_EMAIL`).
 - Expect occasional empty results, login challenges, and outright bans.
 - Use a throwaway account. Never your main.
"""
from __future__ import annotations
import asyncio
import json
import os
import time
from pathlib import Path

from .base import Connector, Post


COOKIE_PATH = Path("info/x_cookies.json")


async def _login_client():
    from twikit import Client
    client = Client(language="en-US")
    if COOKIE_PATH.exists():
        try:
            client.set_cookies(json.loads(COOKIE_PATH.read_text()))
            return client
        except Exception:
            pass
    user = os.environ.get("X_USERNAME")
    pw = os.environ.get("X_PASSWORD")
    email = os.environ.get("X_EMAIL")
    if not (user and pw):
        return None
    try:
        await client.login(auth_info_1=user, auth_info_2=email or user, password=pw)
    except Exception:
        return None
    try:
        COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)
        COOKIE_PATH.write_text(json.dumps(client.get_cookies()))
    except Exception:
        pass
    return client


async def _search(query: str, limit: int) -> list[Post]:
    client = await _login_client()
    if client is None:
        return []
    out: list[Post] = []
    try:
        tweets = await client.search_tweet(query, "Latest")
    except Exception:
        return []
    for t in (tweets or [])[:limit]:
        text = (getattr(t, "text", "") or "").strip()
        if not text:
            continue
        ts = 0
        created = getattr(t, "created_at", None)
        if created:
            try:
                from email.utils import parsedate_to_datetime
                ts = int(parsedate_to_datetime(str(created)).timestamp())
            except Exception:
                ts = 0
        out.append(Post(
            id=f"x:{getattr(t, 'id', abs(hash(text)) % (10**12))}",
            source="x",
            text=text[:2000],
            author=str(getattr(getattr(t, "user", None), "screen_name", "") or "") or None,
            url=f"https://x.com/i/web/status/{getattr(t, 'id', '')}",
            ts=ts or int(time.time()),
            reactions=int(getattr(t, "favorite_count", 0) or 0),
            comments=int(getattr(t, "reply_count", 0) or 0),
            shares=int(getattr(t, "retweet_count", 0) or 0),
            raw={"lang": getattr(t, "lang", None)},
        ))
    return out


class XConnector(Connector):
    name = "x"

    def fetch(self, query: str, limit: int = 30) -> list[Post]:
        try:
            return asyncio.run(_search(query, limit))
        except Exception:
            return []
