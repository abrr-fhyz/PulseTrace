#!/usr/bin/env python3
"""Probe FB scrape state: counts of articles, feeds, url, title, screenshot."""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path


async def probe(query: str = "news", headless: bool = True) -> dict:
    from playwright.async_api import async_playwright

    cookies = json.loads(Path("info/cookies.json").read_text())
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=headless, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ])
        ctx = await b.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        url0 = f"https://www.facebook.com/search/posts/?q={query.replace(' ', '%20')}"
        try:
            await page.goto(url0, wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            await b.close()
            return {"error": f"goto failed: {e}"}

        await asyncio.sleep(4)
        for _ in range(4):
            await page.mouse.wheel(0, 4000)
            await asyncio.sleep(2)

        n_article = await page.locator('div[role="article"]').count()
        n_feed = await page.locator('div[role="feed"]').count()
        n_main = await page.locator('div[role="main"]').count()
        body_text = (await page.locator("body").inner_text())[:600]
        title = await page.title()
        url_now = page.url
        await page.screenshot(path="fb_probe.png", full_page=False)
        await b.close()
        return {
            "url_requested": url0,
            "url_landed": url_now,
            "title": title,
            "article_count": n_article,
            "feed_count": n_feed,
            "main_count": n_main,
            "body_preview": body_text,
        }


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "news"
    hl = "--no-headless" not in sys.argv
    out = asyncio.run(probe(q, headless=hl))
    print(json.dumps(out, indent=2))
