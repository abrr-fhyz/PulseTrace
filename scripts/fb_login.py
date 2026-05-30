#!/usr/bin/env python3
"""Interactive Facebook login -> info/cookies.json.

Launches non-headless Chromium with anti-automation flags, navigates to
facebook.com, waits for the user to complete login (including any 2FA /
checkpoint flow), then exports the cookie jar in the exact format the
FacebookConnector expects.

Usage:
    .venv/bin/python scripts/fb_login.py

Re-run whenever cookies expire (FB rotates ~weekly under heavy use).
"""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path


COOKIE_PATH = Path("info/cookies.json")
REQUIRED = {"c_user", "xs"}  # signals a real authenticated session


async def main() -> int:
    from playwright.async_api import async_playwright

    COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)
    print("Launching Chromium. Login to Facebook in the window that opens.")
    print("When you reach the home feed, come back here and press Enter.\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = await ctx.new_page()
        await page.goto("https://www.facebook.com/", wait_until="domcontentloaded")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, input, "After login completes, press Enter here to save cookies... "
        )

        cookies = await ctx.cookies()
        await browser.close()

    if not cookies:
        print("ERROR: no cookies captured. Browser closed before login finished?")
        return 1

    names = {c["name"] for c in cookies}
    missing = REQUIRED - names
    COOKIE_PATH.write_text(json.dumps(cookies, indent=2))
    print(f"\nWrote {len(cookies)} cookies -> {COOKIE_PATH}")
    if missing:
        print(f"WARNING: missing required cookies {missing!r}. "
              f"Login probably did not complete. Re-run after reaching the feed.")
        return 2
    print("OK: required session cookies present (c_user, xs).")
    print("Test now:  .venv/bin/python -c "
          "\"from lib.connectors.facebook import FacebookConnector as F; "
          "print(len(F().fetch('news', limit=5)))\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
