"""Facebook connector via Playwright + cookies.

WARNING: Facebook actively breaks scrapers. This connector:
 - Requires a valid `info/cookies.json` exported from a logged-in session.
 - Extracts text + engagement from DOM (`[role="article"]`). FB rotates these
   class names; if extraction returns 0, the selectors likely need updating.
 - Heavy: spawns a real Chromium per fetch. Use sparingly.
 - May trip account-security flags. Use a throwaway account.

For screenshot+OCR pipeline (richer engagement counts), keep using
`python main.py scrape` from v1 — that path is preserved.
"""
from __future__ import annotations
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from .base import Connector, Post


COOKIE_PATH = Path("info/cookies.json")
SEARCH_URL = "https://www.facebook.com/search/posts/?q={q}"
DEFAULT_SCROLLS = 4


async def _scrape(query: str, limit: int, headless: bool, scrolls: int) -> list[Post]:
    from playwright.async_api import async_playwright

    if not COOKIE_PATH.exists():
        return []

    cookies = json.loads(COOKIE_PATH.read_text())
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ])
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        )
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        try:
            await page.goto(SEARCH_URL.format(q=query.replace(" ", "%20")),
                            wait_until="domcontentloaded", timeout=30_000)
        except Exception:
            await browser.close()
            return []

        await asyncio.sleep(3)
        for _ in range(scrolls):
            await page.mouse.wheel(0, 4000)
            await asyncio.sleep(2)

        articles = await page.locator('div[role="article"]').all()
        out: list[Post] = []
        seen: set[str] = set()
        for a in articles[: limit * 2]:
            try:
                text = (await a.inner_text()).strip()
            except Exception:
                continue
            if not text or len(text) < 30:
                continue
            sig = text[:120]
            if sig in seen:
                continue
            seen.add(sig)

            reactions, comments = _parse_engagement(text)
            text_clean = "\n".join(
                ln for ln in text.splitlines()
                if ln.strip() and not ln.strip().isdigit()
            )[:2000]

            out.append(Post(
                id=f"facebook:{abs(hash(sig)) % (10**12)}",
                source="facebook",
                text=text_clean,
                author=None,
                url=None,
                ts=int(time.time()),
                reactions=reactions,
                comments=comments,
                shares=0,
                raw={"query": query},
            ))
            if len(out) >= limit:
                break

        await browser.close()
        return out


def _parse_engagement(text: str) -> tuple[int, int]:
    """Best-effort pull of reaction + comment counts from FB post text dump.

    FB inlines counts like '1.2K', '345', '5 comments'. This is fragile.
    """
    import re

    def to_int(s: str) -> int:
        s = s.strip().replace(",", "")
        m = re.match(r"^([\d.]+)\s*([KMB]?)$", s, re.I)
        if not m:
            return 0
        n = float(m.group(1))
        mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(m.group(2).lower(), 1)
        return int(n * mult)

    reactions = 0
    comments = 0
    for m in re.finditer(r"([\d.,]+\s*[KMB]?)\s*comments?", text, re.I):
        comments = max(comments, to_int(m.group(1)))
    for m in re.finditer(r"^([\d.,]+\s*[KMB]?)$", text, re.M):
        reactions = max(reactions, to_int(m.group(1)))
    return reactions, comments


class FacebookConnector(Connector):
    name = "facebook"

    def __init__(self, headless: bool = True, scrolls: int = DEFAULT_SCROLLS) -> None:
        self.headless = headless
        self.scrolls = scrolls

    def fetch(self, query: str, limit: int = 30) -> list[Post]:
        try:
            return asyncio.run(_scrape(query, limit, self.headless, self.scrolls))
        except Exception:
            return []
