"""Stage 18: end-to-end FB-via-OCR through the full v2 pipeline.

One Playwright session → multiple search queries → batched viewport
screenshots → Gemini Vision OCR → Post objects → real embed/cluster/label/
stance + RAG index + Q&A → comprehensive JSON in the same shape as
results/<topic>_result.json.

Skips unless PT_OCR_E2E=1 + cookies + gemini_api_key. Single FB session
reused across queries to minimize anti-bot signal.
"""
from __future__ import annotations
import asyncio
import base64
import json
import os
import re
import time
from pathlib import Path

import numpy as np
import pytest
import requests

from .conftest import REPO_ROOT, RESULTS_DIR, TOPIC, RAG_QUESTIONS


COOKIE_PATH = REPO_ROOT / "info" / "cookies.json"
QUERIES_ENV = os.environ.get("PT_OCR_E2E_QUERIES", "")
SCROLLS_PER_QUERY = int(os.environ.get("PT_OCR_E2E_SCROLLS", "5"))
SHOTS_PER_QUERY = int(os.environ.get("PT_OCR_E2E_SHOTS", "4"))
GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]


def _gemini_key() -> str:
    return (os.environ.get("GEMINI_API_KEY")
            or os.environ.get("gemini_api_key", ""))


def _env_ready() -> tuple[bool, str]:
    if os.environ.get("PT_OCR_E2E", "") != "1":
        return False, "PT_OCR_E2E=1 not set (heavy: Chromium + Vision + full pipeline)"
    if not COOKIE_PATH.exists():
        return False, f"no cookies at {COOKIE_PATH}"
    if not _gemini_key():
        return False, "gemini_api_key missing"
    return True, ""


ready, reason = _env_ready()
pytestmark = pytest.mark.skipif(not ready, reason=reason)


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


def _ocr_screenshot(png_path: Path) -> list[dict]:
    key = _gemini_key()
    b64 = base64.b64encode(png_path.read_bytes()).decode()
    for model in GEMINI_MODELS:
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
                if r.status_code == 429:
                    print(f"  [ocr] {model} 429 throttle, sleeping {4*(attempt+1)}s", flush=True)
                    time.sleep(4 * (attempt + 1))
                    continue
                if r.status_code >= 400:
                    print(f"  [ocr] {model} HTTP {r.status_code}: {r.text[:200]}", flush=True)
                    break
                body = r.json()
                cands = body.get("candidates") or []
                if not cands:
                    print(f"  [ocr] {model} no candidates: {str(body)[:200]}", flush=True)
                    break
                txt = "".join(p.get("text", "") for p in
                              cands[0].get("content", {}).get("parts", [])).strip()
                txt = re.sub(r"^```(?:json)?|```$", "", txt,
                             flags=re.MULTILINE).strip()
                try:
                    parsed = json.loads(txt)
                except Exception as e:
                    print(f"  [ocr] {model} JSON parse fail: {type(e).__name__} text={txt[:200]!r}", flush=True)
                    break
                out = parsed.get("posts") or ([parsed] if "post_content" in parsed else [])
                print(f"  [ocr] {model} OK: {len(out)} posts", flush=True)
                return out
            except requests.HTTPError as e:
                print(f"  [ocr] {model} HTTPError: {e}", flush=True)
                break
            except Exception as e:
                print(f"  [ocr] {model} {type(e).__name__}: {e}", flush=True)
                break
    return []


def _parse_count(s: str) -> int:
    if not isinstance(s, str):
        return int(s or 0)
    s = s.strip().lower().replace(",", "")
    m = re.match(r"([\d.]+)\s*([kmb]?)", s)
    if not m:
        return 0
    n = float(m.group(1))
    mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(m.group(2), 1)
    return int(n * mult)


async def _capture_queries(queries: list[str], shots_per: int,
                           scrolls: int, out_dir: Path) -> dict[str, list[Path]]:
    """One browser session, sequential queries, viewport screenshots each."""
    from playwright.async_api import async_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    cookies = json.loads(COOKIE_PATH.read_text())
    bag: dict[str, list[Path]] = {}

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
        ts = int(time.time())

        for qi, q in enumerate(queries):
            bag[q] = []
            url = f"https://www.facebook.com/search/posts/?q={q.replace(' ', '%20')}"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            except Exception as e:
                print(f"[q={qi}] goto fail: {e}", flush=True)
                continue
            await asyncio.sleep(4)

            shots_taken = 0
            for n in range(scrolls):
                shot = out_dir / f"q{qi}_s{n}_{ts}.png"
                try:
                    await page.screenshot(path=str(shot), full_page=False, timeout=10_000)
                    size = shot.stat().st_size if shot.exists() else 0
                    if size > 30_000:
                        bag[q].append(shot)
                        shots_taken += 1
                        print(f"[q={qi} '{q[:30]}'] shot {n}: {size} bytes",
                              flush=True)
                except Exception as e:
                    print(f"[q={qi}] shot fail: {e}", flush=True)
                if shots_taken >= shots_per:
                    break
                await page.mouse.wheel(0, 3500)
                await asyncio.sleep(1.8)

            # gentle pause between queries to ease anti-bot
            await asyncio.sleep(3)

        await browser.close()
    return bag


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "topic"


def _llm_seed_queries(topic: str, n: int = 3) -> list[str]:
    """Reuse the agent's seed prompt to get topic-driven queries."""
    from lib.llm import chat_json
    try:
        out = chat_json(
            f"Generate {n} diverse, complementary Facebook search queries for "
            "social-media research. Output JSON: {\"queries\":[\"...\"]}",
            f"Topic: {topic}",
            stage="seed",
        )
        qs = [str(q) for q in (out or {}).get("queries", []) if q][:n]
        return qs or [topic]
    except Exception:
        return [topic]


def test_fb_ocr_full_pipeline(tmp_path):
    """Capture FB via OCR, then run embed→cluster→label→stance→RAG."""
    from lib import backend
    from lib.connectors.base import Post
    from lib.embed import embed_texts
    from lib.cluster import cluster_embeddings, centroids, entropy
    from lib.label import label_cluster
    from lib.stance import cluster_sentiment
    from lib.influence import influence as influence_score
    from lib.rag import build_index, ask
    from lib.store import new_run_id, run_dir, write_json

    if QUERIES_ENV:
        queries = [q.strip() for q in QUERIES_ENV.split("|") if q.strip()]
    else:
        queries = _llm_seed_queries(TOPIC, n=3)
    print(f"\n[stage18] topic={TOPIC!r} queries={queries}", flush=True)

    t_cap = time.time()
    shots_by_q = asyncio.run(_capture_queries(
        queries, SHOTS_PER_QUERY, SCROLLS_PER_QUERY,
        tmp_path / "shots",
    ))
    cap_sec = round(time.time() - t_cap, 2)
    total_shots = sum(len(v) for v in shots_by_q.values())
    assert total_shots > 0, "no screenshots captured (FB throttled or cookies stale)"

    t_ocr = time.time()
    posts: list[Post] = []
    raw_ocr: list[dict] = []
    for q, shots in shots_by_q.items():
        for shot in shots:
            extracted = _ocr_screenshot(shot)
            time.sleep(4)
            raw_ocr.append({
                "query": q, "shot": shot.name,
                "n_posts": len(extracted), "extracted": extracted,
            })
            for e in extracted:
                body = (e.get("post_content") or "").strip()
                if len(body) < 30:
                    continue
                pid = f"facebook:{abs(hash(body[:120])) % (10**12)}"
                posts.append(Post(
                    id=pid,
                    source="facebook",
                    text=body,
                    author=e.get("author") or None,
                    url=None,
                    ts=int(time.time()),
                    reactions=_parse_count(str(e.get("reactions", ""))),
                    comments=_parse_count(str(e.get("comments", ""))),
                    shares=_parse_count(str(e.get("shares", ""))),
                    raw={"query": q, "shot": shot.name},
                ))
    # dedup by id
    seen: dict[str, Post] = {}
    for p in posts:
        if p.id not in seen:
            seen[p.id] = p
    posts = list(seen.values())
    ocr_sec = round(time.time() - t_ocr, 2)

    assert posts, "OCR returned 0 usable posts"
    print(f"[stage18] captured={total_shots} ocr_posts={len(posts)} "
          f"cap={cap_sec}s ocr={ocr_sec}s", flush=True)

    rid = new_run_id()
    rundir = run_dir(rid)
    write_json(rid, "run.json", {
        "id": rid, "topic": TOPIC,
        "queries": [{"q": q, "source": "facebook", "iter": 0} for q in queries],
        "stop_reason": "ocr_e2e_complete",
        "metrics": {"posts": len(posts)},
    })
    write_json(rid, "posts.json", [p.to_dict() for p in posts])

    t_emb = time.time()
    texts = [p.text for p in posts]
    emb = embed_texts(texts)
    emb_sec = round(time.time() - t_emb, 2)
    assert emb.shape[0] == len(posts), "embed row count mismatch"

    t_cl = time.time()
    labels = cluster_embeddings(emb, min_cluster_size=2)
    cents = centroids(emb, labels)
    H = entropy(labels)
    cl_sec = round(time.time() - t_cl, 2)

    cluster_view: list[dict] = []
    t_lbl = time.time()
    for cid, vec in cents.items():
        member_idx = [i for i, lab in enumerate(labels) if lab == cid]
        member_posts = [posts[i] for i in member_idx]
        member_texts = [p.text for p in member_posts]
        try:
            lab = label_cluster(member_texts[:8])
        except Exception as e:
            lab = {"label": f"cluster {cid}", "desc": f"label_error: {e}"}
        try:
            sent = cluster_sentiment(lab.get("label", "topic"), member_texts[:30])
        except Exception as e:
            sent = {"pos": 0.0, "neu": 1.0, "neg": 0.0, "error": str(e)}

        ranked = sorted(member_posts,
                        key=lambda p: influence_score(p), reverse=True)[:6]
        cluster_view.append({
            "id": int(cid),
            "label": lab.get("label", f"cluster {cid}"),
            "desc": lab.get("desc", ""),
            "n_members": len(member_idx),
            "centroid": vec.tolist(),
            "sentiment": sent,
            "sentiment_pct": {
                "pos": round(sent.get("pos", 0.0) * 100, 1),
                "neu": round(sent.get("neu", 0.0) * 100, 1),
                "neg": round(sent.get("neg", 0.0) * 100, 1),
            },
            "top_posts": [{
                "id": p.id, "author": p.author,
                "text": p.text[:400],
                "reactions": p.reactions, "comments": p.comments, "shares": p.shares,
                "influence": round(influence_score(p), 4),
            } for p in ranked],
        })
    lbl_sec = round(time.time() - t_lbl, 2)
    write_json(rid, "clusters.json", cluster_view)

    # cytoscape-style graph
    nodes = [{"data": {
        "id": str(c["id"]), "label": c["label"],
        "size": c["n_members"], "sentiment": c["sentiment"],
    }} for c in cluster_view]
    edges = []
    arr = list(cluster_view)
    for i, a in enumerate(arr):
        va = np.array(a["centroid"])
        for b in arr[i + 1:]:
            vb = np.array(b["centroid"])
            denom = float(np.linalg.norm(va) * np.linalg.norm(vb)) or 1.0
            sim = float(va @ vb) / denom
            if sim > 0.5:
                edges.append({"data": {
                    "id": f"{a['id']}-{b['id']}",
                    "source": str(a["id"]), "target": str(b["id"]),
                    "weight": round(sim, 4),
                }})

    t_rag = time.time()
    try:
        build_index(rid)
    except Exception as e:
        print(f"[stage18] build_index error: {e}", flush=True)
    rag_qa = []
    for q in RAG_QUESTIONS:
        try:
            r = ask(rid, q, k=5)
            rag_qa.append({
                "question": q,
                "answer": r.get("answer", ""),
                "citations": r.get("citations", []),
                "n_retrieved": len(r.get("retrieved", [])),
            })
        except Exception as e:
            rag_qa.append({"question": q, "error": str(e)})
    rag_sec = round(time.time() - t_rag, 2)

    news_items = sorted([{
        "id": p.id, "author": p.author,
        "source": p.source, "url": p.url,
        "text": p.text,
        "reactions": p.reactions, "comments": p.comments, "shares": p.shares,
        "ts": p.ts,
        "influence": round(influence_score(p), 4),
    } for p in posts], key=lambda x: x["influence"], reverse=True)

    persistent_shots = REPO_ROOT / "test_artifacts" / "stage18_shots"
    persistent_shots.mkdir(parents=True, exist_ok=True)
    for shots in shots_by_q.values():
        for s in shots:
            try:
                (persistent_shots / s.name).write_bytes(s.read_bytes())
            except Exception:
                pass

    payload = {
        "topic": TOPIC,
        "run_id": rid,
        "generated_at": int(time.time()),
        "providers": {
            "chat": {"name": "cascade", "stage_tags": ["seed", "label", "stance", "rag"]},
            "embed": {"name": backend.embed_provider().name,
                      "model": backend.embed_provider().embed_model},
            "vision": {"name": "gemini", "models": GEMINI_MODELS},
        },
        "timings_sec": {
            "capture": cap_sec, "ocr": ocr_sec,
            "embed": emb_sec, "cluster_label": cl_sec + lbl_sec,
            "rag": rag_sec,
        },
        "kpis": {
            "queries": len(queries),
            "screenshots": total_shots,
            "posts": len(posts),
            "clusters": len(cluster_view),
            "entropy": round(H, 4),
            "by_source": {"facebook": len(posts)},
        },
        "search_log": [
            {"iter": 0, "queries": [{"q": q, "source": "facebook"} for q in queries]},
        ],
        "ocr_raw": raw_ocr,
        "clusters": cluster_view,
        "graph": {"nodes": nodes, "edges": edges},
        "news_items": news_items,
        "rag_qa": rag_qa,
        "shots_dir": str(persistent_shots.relative_to(REPO_ROOT)),
        "run_dir": str(rundir),
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"{_slug(TOPIC)}_ocr_e2e.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    write_json(rid, "ocr_e2e_payload.json", payload)
    print(f"\n[stage18] wrote {out_path.relative_to(REPO_ROOT)} "
          f"({out_path.stat().st_size} bytes)")
    print(f"[stage18] posts={len(posts)} clusters={len(cluster_view)} "
          f"entropy={H:.3f} rag_q={len(rag_qa)}")

    assert len(cluster_view) >= 1, "no clusters produced"
    assert any(c["top_posts"] for c in cluster_view), "clusters have no top_posts"
