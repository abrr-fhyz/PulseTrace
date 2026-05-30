"""Stage 17: v1-style screenshot + Vision OCR (Gemini variant).

DOM-based FacebookConnector returns 0 posts: FB CSS-scrambles letters across
spans so `inner_text` yields gibberish, then the >30-char filter drops every
candidate. The screenshot path bypasses the scramble (pixels survive CSS
reorder). lib/catalogue.py uses OpenAI Vision; this stage exercises the same
extraction shape via Gemini Vision (only key the project ships with).

 1. Reuse info/cookies.json to skip email/password login.
 2. Drive Playwright Chromium to facebook.com/search/posts/?q=<topic>.
 3. Capture up to PT_OCR_LIMIT article screenshots.
 4. Send each as inline_data to gemini-2.5-flash via REST.
 5. Assert >=1 screenshot yields non-empty `post_content`.

Heavy. Skips unless PT_OCR_TEST=1 + cookies + gemini_api_key all set.
"""
from __future__ import annotations
import asyncio
import base64
import json
import os
import re
import time
from pathlib import Path

import pytest
import requests

from .conftest import REPO_ROOT, RESULTS_DIR


COOKIE_PATH = REPO_ROOT / "info" / "cookies.json"
PROBE_QUERY = os.environ.get("PT_OCR_QUERY", "Donald Trump")
PROBE_LIMIT = int(os.environ.get("PT_OCR_LIMIT", "3"))
PROBE_SCROLLS = int(os.environ.get("PT_OCR_SCROLLS", "5"))
GEMINI_MODEL = os.environ.get("PT_OCR_MODEL", "gemini-2.5-flash")


def _gemini_key() -> str:
    return (os.environ.get("GEMINI_API_KEY")
            or os.environ.get("gemini_api_key", ""))


def _env_ready() -> tuple[bool, str]:
    if os.environ.get("PT_OCR_TEST", "") != "1":
        return False, "PT_OCR_TEST=1 not set (heavy: Chromium + Gemini Vision)"
    if not COOKIE_PATH.exists():
        return False, f"no cookies at {COOKIE_PATH} — run scripts/fb_login.py"
    if not _gemini_key():
        return False, "gemini_api_key missing (.env.api_keys)"
    return True, ""


ready, reason = _env_ready()
pytestmark = pytest.mark.skipif(not ready, reason=reason)


async def _capture(query: str, limit: int, scrolls: int, out_dir: Path) -> list[Path]:
    from playwright.async_api import async_playwright

    cookies = json.loads(COOKIE_PATH.read_text())
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ])
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        url = f"https://www.facebook.com/search/posts/?q={query.replace(' ', '%20')}"
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(4)

        async def save_viewport(name: str) -> None:
            if len(saved) >= limit:
                return
            shot = out_dir / name
            try:
                await page.screenshot(path=str(shot), full_page=False, timeout=10_000)
                size = shot.stat().st_size if shot.exists() else 0
                print(f"[capture] viewport {name}: {size} bytes", flush=True)
                if size > 20_000:
                    saved.append(shot)
            except Exception as e:
                print(f"[capture] viewport fail {name}: {e}", flush=True)

        ts = int(time.time())
        await save_viewport(f"fb_{ts}_viewport_0.png")

        for n in range(scrolls):
            await page.mouse.wheel(0, 3500)
            await asyncio.sleep(1.8)
            await save_viewport(f"fb_{ts}_viewport_{n + 1}.png")
            if len(saved) >= limit:
                break

        try:
            await page.wait_for_selector('div[role="article"]', timeout=15_000)
        except Exception as e:
            print(f"[capture] wait_for_selector failed: {e}", flush=True)
        articles = await page.locator('div[role="article"]').all()
        print(f"[capture] found {len(articles)} article elements", flush=True)
        errors: list[str] = []
        for i, a in enumerate(articles):
            if len(saved) >= limit:
                break
            try:
                try:
                    await a.scroll_into_view_if_needed(timeout=4000)
                    await asyncio.sleep(0.6)
                except Exception:
                    pass
                # Skip loading skeletons: articles with no real content.
                try:
                    txt = (await a.inner_text(timeout=3000)).strip()
                except Exception:
                    txt = ""
                if len(txt) < 60:
                    print(f"[capture] skip {i}: only {len(txt)} chars text "
                          f"(likely skeleton)", flush=True)
                    continue
                box = await a.bounding_box()
                if not box or box["height"] < 120:
                    print(f"[capture] skip {i}: box too small ({box})",
                          flush=True)
                    continue
                shot = out_dir / f"fb_{ts}_{i}.png"
                await a.screenshot(path=str(shot), timeout=10_000)
                size = shot.stat().st_size if shot.exists() else 0
                print(f"[capture] shot {i}: {size} bytes, text_len={len(txt)}",
                      flush=True)
                if size > 5_000:
                    saved.append(shot)
            except Exception as e:
                errors.append(f"i={i}: {type(e).__name__}: {e}")
                continue
        if errors:
            print(f"[capture] errors: {errors[:3]}", flush=True)
        # Fallback: full-page screenshot for inspection
        if not saved:
            full = out_dir / "fullpage.png"
            try:
                await page.screenshot(path=str(full), full_page=True)
                size = full.stat().st_size if full.exists() else 0
                print(f"[capture] saved fallback fullpage: {size} bytes", flush=True)
                if size > 20_000:
                    saved.append(full)
            except Exception as e:
                print(f"[capture] fullpage fail: {e}", flush=True)
        await browser.close()

    return saved


OCR_PROMPT = (
    "Extract this Facebook post screenshot. Return ONLY a JSON object:\n"
    "{\n"
    '  "author": "name of original poster",\n'
    '  "post_content": "full visible post text, empty string if none",\n'
    '  "reactions": "reactions count as string e.g. \\"1.2K\\" or empty",\n'
    '  "comments": "comments count as string or empty",\n'
    '  "shares": "shares count as string or empty"\n'
    "}\n"
    "No prose. No markdown fence. JSON only."
)


def _gemini_ocr_once(png_path: Path, model: str) -> dict:
    key = _gemini_key()
    b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    payload = {
        "contents": [{
            "parts": [
                {"text": OCR_PROMPT},
                {"inline_data": {"mime_type": "image/png", "data": b64}},
            ],
        }],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
        },
    }
    r = requests.post(url, json=payload, timeout=60)
    r.raise_for_status()
    body = r.json()
    cands = body.get("candidates") or []
    if not cands:
        return {"error": "no candidates", "raw": body}
    parts = cands[0].get("content", {}).get("parts") or []
    txt = "".join(p.get("text", "") for p in parts).strip()
    txt = re.sub(r"^```(?:json)?|```$", "", txt, flags=re.MULTILINE).strip()
    try:
        return json.loads(txt)
    except Exception:
        return {"error": "non-json", "raw_text": txt[:600]}


def _gemini_ocr(png_path: Path) -> dict:
    """Retry across rate limits + model fallback (2.0-flash -> 1.5-flash)."""
    models = [
        GEMINI_MODEL,
        "gemini-2.5-flash-lite",
    ]
    last_err: dict = {}
    for m in models:
        for attempt in range(3):
            try:
                return _gemini_ocr_once(png_path, m)
            except requests.HTTPError as e:
                code = getattr(e.response, "status_code", 0)
                if code == 429:
                    sleep_s = 8 * (attempt + 1)
                    print(f"[ocr] 429 on {m} attempt {attempt+1}, "
                          f"sleeping {sleep_s}s", flush=True)
                    time.sleep(sleep_s)
                    continue
                detail = ""
                try:
                    detail = (e.response.text or "")[:300]
                except Exception:
                    detail = ""
                last_err = {"error": f"HTTP {code}", "model": m, "detail": detail}
                break
            except Exception as e:
                last_err = {"error": f"{type(e).__name__}: {e}", "model": m}
                break
    return last_err or {"error": "all models exhausted"}


def test_v1_ocr_pipeline_extracts_real_post_text(tmp_path):
    shots_dir = tmp_path / "shots"
    t0 = time.time()
    shots = asyncio.run(_capture(PROBE_QUERY, PROBE_LIMIT, PROBE_SCROLLS, shots_dir))
    capture_sec = round(time.time() - t0, 2)

    assert shots, (
        f"captured 0 screenshots for {PROBE_QUERY!r}. Cookies stale or "
        "FB selector 'div[role=\"article\"]' rotated. Re-login + inspect "
        "facebook.com/search/posts manually."
    )

    t1 = time.time()
    results: list[dict] = []
    for png in shots:
        try:
            r = _gemini_ocr(png)
            r["filename"] = png.name
            r["bytes"] = png.stat().st_size
        except Exception as e:
            r = {"error": f"{type(e).__name__}: {e}", "filename": png.name}
        results.append(r)
    ocr_sec = round(time.time() - t1, 2)

    non_empty = [
        r for r in results
        if isinstance(r, dict) and (r.get("post_content") or "").strip()
    ]

    persistent_shots = REPO_ROOT / "test_artifacts" / "stage17_shots"
    persistent_shots.mkdir(parents=True, exist_ok=True)
    for s in shots:
        try:
            (persistent_shots / s.name).write_bytes(s.read_bytes())
        except Exception:
            pass

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / "stage17_v1_ocr.json"
    out_path.write_text(json.dumps({
        "query": PROBE_QUERY,
        "model": GEMINI_MODEL,
        "asked": PROBE_LIMIT,
        "captured": len(shots),
        "ocr_non_empty": len(non_empty),
        "capture_sec": capture_sec,
        "ocr_sec": ocr_sec,
        "shots_dir": str(persistent_shots.relative_to(REPO_ROOT)),
        "samples": results,
    }, indent=2, default=str))
    print(f"\n[stage17] captured={len(shots)} ocr_non_empty={len(non_empty)} "
          f"capture={capture_sec}s ocr={ocr_sec}s -> "
          f"{out_path.relative_to(REPO_ROOT)}")

    if not non_empty:
        pytest.fail(
            f"captured {len(shots)} screenshots but Vision extracted 0 "
            "post_content. Inspect "
            f"{out_path.relative_to(REPO_ROOT)} + "
            f"{persistent_shots.relative_to(REPO_ROOT)}/"
        )
