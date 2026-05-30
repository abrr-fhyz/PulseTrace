"""Stage 8: full agent run -> single JSON written to repo root.

Picks the first chat provider that survived Stage 2 logic (re-probed here so
this file is runnable in isolation) and pairs it with an embedding-capable
provider. Saves the merged result to `<topic_slug>_result.json`.
"""
from __future__ import annotations
import json
import os
import re
import time
from pathlib import Path

import pytest
import requests

from .conftest import TOPIC, CHAT_PROVIDERS, has_key, REPO_ROOT, RESULTS_DIR


def _pick_chat(monkeypatch) -> str | None:
    from lib import backend
    from lib.llm import chat_json
    for prov in CHAT_PROVIDERS:
        if not has_key(prov):
            continue
        monkeypatch.setenv("PULSETRACE_BACKEND", prov)
        try:
            out = chat_json('Reply ONLY JSON {"ok":true}.', "ping", max_tokens=30)
            if isinstance(out, dict) and out.get("ok") in (True, "true", 1):
                return prov
        except Exception:
            continue
    return None


def _pick_embed() -> str | None:
    try:
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        if requests.get(f"{host}/api/tags", timeout=3).status_code == 200:
            return "ollama"
    except Exception:
        pass
    if has_key("gemini"):
        return "gemini"
    return None


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "topic"


def test_full_agent_writes_root_json(monkeypatch):
    chat = _pick_chat(monkeypatch)
    embed = _pick_embed()
    if not chat:
        pytest.skip("no chat provider working")
    if not embed:
        pytest.skip("no embed provider available")

    monkeypatch.setenv("PULSETRACE_BACKEND", chat)
    monkeypatch.setenv("PULSETRACE_EMBED_BACKEND", embed)

    from lib import agent, backend, store
    monkeypatch.setattr(agent, "MAX_ITERS", 2)
    monkeypatch.setattr(agent, "MAX_POSTS", 40)

    sources = ["facebook"]
    t0 = time.time()
    run_id = agent.run_agent(TOPIC, sources)
    elapsed = time.time() - t0
    assert run_id

    run = store.read_json(run_id, "run.json") or {}
    posts = store.read_json(run_id, "posts.json") or []
    clusters = store.read_json(run_id, "clusters.json") or []

    payload = _build_webapp_payload(
        topic=TOPIC, chat=chat, embed=embed, run_id=run_id,
        elapsed=elapsed, run=run, posts=posts, clusters=clusters,
    )

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"{_slug(TOPIC)}_result.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n[stage08] wrote {out_path}  ({out_path.stat().st_size} bytes)")
    print(f"[stage08] chat={chat}  embed={embed}  posts={len(posts)}  "
          f"clusters={len(clusters)}  stop={run.get('stop_reason')}")

    assert out_path.exists()
    assert run.get("topic") == TOPIC
    # Surface real pipeline failures; tolerate exotic topics with no coverage.
    # embed_error is only a real failure if no clusters were ever produced.
    # A later-iter embed hiccup still leaves a usable run from the earlier iter.
    if run.get("stop_reason") == "embed_error" and not clusters:
        pytest.fail(f"agent halted at embed stage with no clusters "
                    f"(stop_reason={run['stop_reason']}). Check stage 03 "
                    f"with provider={embed}.")
    if len(posts) == 0:
        pytest.skip(f"agent produced 0 posts for topic {TOPIC!r}. "
                    f"Pipeline OK; topic has no source coverage. "
                    f"Root JSON still written.")


def _by_source(posts: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in posts:
        s = (p or {}).get("source") or "?"
        out[s] = out.get(s, 0) + 1
    return out


def _build_webapp_payload(*, topic, chat, embed, run_id, elapsed, run, posts, clusters):
    """Shape matches what server.py's /graph + /run-info endpoints expose,
    so the JSON file is enough to reproduce every panel of the dashboard:
    KPIs, sentiment-per-cluster (with %), topic graph, ranked posts with
    influence + newslinks, and the full search-query log per iteration."""
    import numpy as np
    from lib import backend
    from lib.influence import influence as _influence_score
    from lib.connectors.base import Post as _Post

    posts_by_id = {p.get("id"): p for p in posts}

    def _influence_for(pdict):
        return round(_influence_score(_Post(
            id=pdict.get("id", ""), source=pdict.get("source", ""),
            text=pdict.get("text", ""),
            reactions=int(pdict.get("reactions") or 0),
            comments=int(pdict.get("comments") or 0),
            shares=int(pdict.get("shares") or 0),
            ts=int(pdict.get("ts") or 0),
        )), 4)

    cluster_view = []
    for c in clusters:
        member_ids = c.get("members", [])
        # Re-rank members by influence so the dashboard's "top_posts" panel
        # is reproducible directly from the JSON.
        members_full = [posts_by_id[m] for m in member_ids if m in posts_by_id]
        members_ranked = sorted(
            members_full, key=_influence_for, reverse=True)[:8]

        samples = [{
            "id": p.get("id"),
            "source": p.get("source"),
            "url": p.get("url"),
            "author": p.get("author"),
            "text_preview": (p.get("text") or "")[:400],
            "reactions": p.get("reactions", 0),
            "comments": p.get("comments", 0),
            "shares": p.get("shares", 0),
            "ts": p.get("ts", 0),
            "influence": _influence_for(p),
        } for p in members_ranked]

        sent = c["sentiment"]
        cluster_view.append({
            "id": c["id"],
            "label": c["label"],
            "desc": c.get("desc", ""),
            "n_members": len(member_ids),
            "sentiment": sent,
            "sentiment_pct": {
                "pos": round(sent.get("pos", 0.0) * 100, 1),
                "neu": round(sent.get("neu", 0.0) * 100, 1),
                "neg": round(sent.get("neg", 0.0) * 100, 1),
            },
            "top_posts": samples,
        })

    # Cytoscape-style graph (mirrors /graph endpoint).
    nodes, edges = [], []
    for c in clusters:
        nodes.append({
            "data": {
                "id": str(c["id"]),
                "label": c["label"],
                "size": len(c.get("members", [])),
                "sentiment": c["sentiment"],
            }
        })
    for i, a in enumerate(clusters):
        if "centroid" not in a:
            continue
        va = np.array(a["centroid"])
        for b in clusters[i + 1:]:
            if "centroid" not in b:
                continue
            vb = np.array(b["centroid"])
            denom = float(np.linalg.norm(va) * np.linalg.norm(vb)) or 1.0
            sim = float(va @ vb) / denom
            if sim > 0.5:
                edges.append({"data": {
                    "id": f"{a['id']}-{b['id']}",
                    "source": str(a["id"]),
                    "target": str(b["id"]),
                    "weight": round(sim, 4),
                }})

    # Flat post list with the news-link / source-link the UI links out to,
    # already ranked by influence so the "most influential opinion" use-case
    # is one indexing away.
    news_items_unsorted = [{
        "id": p.get("id"),
        "source": p.get("source"),
        "url": p.get("url"),
        "author": p.get("author"),
        "text": p.get("text"),
        "reactions": p.get("reactions", 0),
        "comments": p.get("comments", 0),
        "shares": p.get("shares", 0),
        "ts": p.get("ts", 0),
        "influence": _influence_for(p),
    } for p in posts]
    news_items = sorted(news_items_unsorted, key=lambda x: x["influence"], reverse=True)

    # Group the agent's search-query log by iteration so the README's
    # "Step 1 — generate queries" panel renders straight from this JSON.
    queries_by_iter: dict[int, list[dict]] = {}
    for q in run.get("queries", []):
        queries_by_iter.setdefault(int(q.get("iter", 0)), []).append({
            "q": q.get("q"), "source": q.get("source"),
        })
    search_log = [{"iter": k, "queries": queries_by_iter[k]}
                  for k in sorted(queries_by_iter)]

    # Cluster-level entropy proxy: distribution of cluster sizes.
    sizes = np.array([c["n_members"] for c in cluster_view], dtype=float)
    if sizes.sum() > 0:
        p = sizes / sizes.sum()
        H = float(-(p * np.log(p + 1e-12)).sum())
    else:
        H = 0.0

    return {
        "topic": topic,
        "run_id": run_id,
        "generated_at": int(time.time()),
        "elapsed_sec": round(elapsed, 2),
        "providers": {
            "chat":  {"name": chat,  "model": backend.PROVIDERS[chat].chat_model},
            "embed": {"name": embed, "model": backend.PROVIDERS[embed].embed_model},
        },
        "stop_reason": run.get("stop_reason"),
        "kpis": {
            "posts": len(posts),
            "clusters": len(clusters),
            "entropy": round(H, 4),
            "by_source": _by_source(posts),
        },
        "search_log": search_log,
        "queries": run.get("queries", []),
        "clusters": cluster_view,
        "graph": {"nodes": nodes, "edges": edges},
        "news_items": news_items,
        "raw_run": run,
    }
