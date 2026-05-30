"""Facebook connector — viewport screenshots + Gemini Vision OCR.

DOM extraction is dead: FB scrambles text across rotating span class names so
`inner_text()` returns short useless fragments. Instead this connector does
what tests/stages/test_18_fb_ocr_e2e.py proved works:
 1. cookies.json -> Playwright Chromium
 2. goto search URL, wait, scroll N times, screenshot the viewport each scroll
 3. send each screenshot to gemini-2.5-flash Vision REST endpoint with a
    structured JSON prompt; fall back to flash-lite on 429
 4. parse posts, dedupe by content hash, return Post list

Requires:
 - info/cookies.json (logged-in browser cookies)
 - GEMINI_API_KEY (or gemini_api_key) in env
"""
from __future__ import annotations
import asyncio
import base64
import json
import os
import re
import tempfile
import time
from pathlib import Path

import requests

from .base import Connector, Post
from .. import backend


COOKIE_PATH = Path("info/cookies.json")
SEARCH_URL = "https://www.facebook.com/search/posts/?q={q}"

DEFAULT_SCROLLS = int(os.environ.get("PT_FB_SCROLLS", "5"))
DEFAULT_SHOTS = int(os.environ.get("PT_FB_SHOTS", "4"))
SHOT_MIN_BYTES = 30_000

OCR_PROMPT = (
    "This screenshot shows one or more Facebook posts in a feed. Extract every "
    "visible post and return ONLY a JSON object of this exact shape:\n"
    '{"posts":[{"author":"page or person name","post_content":"full visible '
    'post text","reactions":"number e.g. 1.2K or empty","comments":"e.g. 311 '
    'comments or empty","shares":"e.g. 103 shares or empty"}]}\n'
    "If a card shows no body text (image-only), set post_content to a short "
    "objective description of the image instead. Skip empty skeleton "
    "placeholders. No prose, no markdown, JSON only."
)


def _gemini_key() -> str:
    return (os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("gemini_api_key", ""))


def _vision_models() -> list[str]:
    primary = backend.GEMINI_VISION_MODEL
    fallback = "gemini-2.5-flash-lite"
    return [primary] if primary == fallback else [primary, fallback]


def _ocr(png_path: Path, key: str) -> list[dict]:
    b64 = base64.b64encode(png_path.read_bytes()).decode()
    for model in _vision_models():
        for attempt in range(3):
            try:
                url = (f"https://generativelanguage.googleapis.com/v1beta/"
                       f"models/{model}:generateContent?key={key}")
                r = requests.post(url, json={
                    "contents": [{"parts": [
                        {"text": OCR_PROMPT},
                        {"inline_data": {"mime_type": "image/png", "data": b64}},
                    ]}],
                    "generationConfig": {
                        "temperature": 0.0,
                        "responseMimeType": "application/json",
                    },
                }, timeout=60)
            except requests.RequestException:
                break
            if r.status_code == 429:
                time.sleep(4 * (attempt + 1))
                continue
            if r.status_code >= 400:
                break
            body = r.json()
            cands = body.get("candidates") or []
            if not cands:
                break
            txt = "".join(p.get("text", "") for p in
                          cands[0].get("content", {}).get("parts", [])).strip()
            txt = re.sub(r"^```(?:json)?|```$", "", txt, flags=re.MULTILINE).strip()
            try:
                parsed = json.loads(txt)
            except json.JSONDecodeError:
                break
            posts = parsed.get("posts") or ([parsed] if "post_content" in parsed else [])
            return posts
    return []


def _parse_count(s: object) -> int:
    if not isinstance(s, str):
        try:
            return int(s or 0)
        except (TypeError, ValueError):
            return 0
    s = s.strip().lower().replace(",", "")
    m = re.match(r"([\d.]+)\s*([kmb]?)", s)
    if not m:
        return 0
    n = float(m.group(1))
    mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(m.group(2), 1)
    return int(n * mult)


async def _capture(query: str, scrolls: int, shots_per: int,
                   out_dir: Path) -> list[Path]:
    from playwright.async_api import async_playwright

    if not COOKIE_PATH.exists():
        return []
    cookies = json.loads(COOKIE_PATH.read_text())
    shots: list[Path] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ])
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
            viewport={"width": 1280, "height": 900},
        )
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        try:
            await page.goto(SEARCH_URL.format(q=query.replace(" ", "%20")),
                            wait_until="domcontentloaded", timeout=30_000)
        except Exception:
            await browser.close()
            return []
        await asyncio.sleep(4)
        ts = int(time.time())
        for n in range(scrolls):
            shot = out_dir / f"q_{n}_{ts}.png"
            try:
                await page.screenshot(path=str(shot), full_page=False, timeout=10_000)
            except Exception:
                continue
            if shot.exists() and shot.stat().st_size > SHOT_MIN_BYTES:
                shots.append(shot)
            if len(shots) >= shots_per:
                break
            await page.mouse.wheel(0, 3500)
            await asyncio.sleep(1.8)
        await browser.close()
    return shots


def _shots_to_posts(query: str, shots: list[Path], key: str,
                    limit: int) -> list[Post]:
    seen: set[str] = set()
    out: list[Post] = []
    for shot in shots:
        for e in _ocr(shot, key):
            body = (e.get("post_content") or "").strip()
            if len(body) < 30:
                continue
            sig = body[:160]
            if sig in seen:
                continue
            seen.add(sig)
            out.append(Post(
                id=f"facebook:{abs(hash(sig)) % (10**12)}",
                source="facebook",
                text=body[:2000],
                author=(e.get("author") or None),
                url=None,
                ts=int(time.time()),
                reactions=_parse_count(e.get("reactions", "")),
                comments=_parse_count(e.get("comments", "")),
                shares=_parse_count(e.get("shares", "")),
                raw={"query": query, "shot": shot.name},
            ))
            if len(out) >= limit:
                return out
        time.sleep(2)
    return out


class FacebookConnector(Connector):
    name = "facebook"

    def __init__(self, headless: bool = True, scrolls: int = DEFAULT_SCROLLS,
                 shots: int = DEFAULT_SHOTS) -> None:
        self.headless = headless
        self.scrolls = scrolls
        self.shots = shots

    def fetch(self, query: str, limit: int = 30) -> list[Post]:
        key = _gemini_key()
        if not key or not COOKIE_PATH.exists():
            return []
        with tempfile.TemporaryDirectory(prefix="fbshots_") as td:
            try:
                shots = asyncio.run(_capture(query, self.scrolls, self.shots, Path(td)))
            except Exception:
                return []
            if not shots:
                return []
            try:
                return _shots_to_posts(query, shots, key, limit)
            except Exception:
                return []
