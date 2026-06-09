"""Agent loop: seed queries -> fetch -> cluster -> label -> expand or stop."""
from __future__ import annotations
import time
from concurrent.futures import ThreadPoolExecutor
from .connectors.base import Connector, Post
from .connectors.reddit import RedditConnector
from .connectors.hn import HNConnector
from .connectors.facebook import FacebookConnector
from .connectors.x import XConnector
from .connectors.instagram import InstagramConnector
from .connectors.youtube import YouTubeConnector
from .connectors.polymarket import PolymarketConnector
from .connectors.github import GitHubConnector
from .connectors.bluesky import BlueskyConnector
from .embed import embed_texts
from .dedup import near_dupe_keep
from .cluster import cluster_embeddings, centroids, entropy, saturation
from .label import label_cluster
from .stance import cluster_sentiments
from .relevance import token_overlap_relevance, extract_core_subject
from .rerank import rank_posts, llm_rerank
from .events import BUS
from .store import write_json, new_run_id
from .llm import chat_json
from .evidence import build as build_evidence


MAX_ITERS = 4
MAX_POSTS = 500
EPS = 0.05
SAT_EPS = 0.8
REL_FLOOR = 0.12          # posts below this relevance to the topic are noise
RERANK_SHORTLIST = 30     # candidates sent to the LLM relevance reranker
MIN_ONTOPIC = 6           # keep all posts if fewer survive the gate (recall guard)
EXPAND_REL_FLOOR = 0.12   # drop expansion queries that drift off the core subject
SOURCES: dict[str, type[Connector]] = {
    "reddit": RedditConnector,
    "hn": HNConnector,
    "facebook": FacebookConnector,
    "x": XConnector,
    "instagram": InstagramConnector,
    "youtube": YouTubeConnector,
    "polymarket": PolymarketConnector,
    "github": GitHubConnector,
    "bluesky": BlueskyConnector,
}


_SEED_NEUTRAL = (
    "Generate 5 diverse, complementary search queries for social-media research "
    'on the user\'s topic. Output JSON: {"queries": ["..."]}'
)
_SEED_OPINION = (
    "Generate 6 diverse search queries for social-media research on the topic. "
    "The user holds an opinion. Half the queries must seek evidence SUPPORTING "
    "the opinion, half must seek evidence CHALLENGING / against it. "
    'Output JSON: {"queries": ["..."]}'
)


def _llm_seed(topic: str, opinion: str | None = None) -> list[str]:
    system = _SEED_OPINION if opinion else _SEED_NEUTRAL
    cap = 6 if opinion else 5
    user = f"Topic: {topic}"
    if opinion:
        user += f'\nUser opinion: "{opinion}"'
    try:
        out = chat_json(system, user, stage="seed")
    except Exception:
        return [topic]
    qs = [str(q) for q in out.get("queries", []) if q]
    return qs[:cap] or [topic]


def _llm_next(topic: str, labels: list[str], opinion: str | None = None) -> dict:
    extra = (
        f' The user opinion is "{opinion}"; prioritize under-covered angles that '
        "could support OR challenge it."
        if opinion else ""
    )
    system = (
        "Given cluster labels found so far and the topic, decide: stop or expand. "
        "If expand, propose up to 3 new search queries targeting under-covered "
        "angles. Every query MUST stay about the topic's core subject — do not "
        "drift to adjacent themes a label happened to surface (e.g. if the topic "
        "is a technology, do not pivot to job-hunting or resumes)." + extra +
        ' Output JSON: {"action": "stop"|"expand", "queries": ["..."]}'
    )
    try:
        return chat_json(system, f"Topic: {topic}\nLabels so far:\n- " + "\n- ".join(labels), stage="next")
    except Exception:
        return {"action": "stop", "queries": []}


def _build_connector(src: str, run_id: str | None,
                     iter_no: int) -> Connector | None:
    cls = SOURCES.get(src)
    if cls is None:
        return None
    if src == "facebook" and run_id:
        from .store import run_dir
        shots_dir = run_dir(run_id) / "shots" / f"iter_{iter_no}"
        try:
            return cls(shots_dir=shots_dir)
        except TypeError:
            pass
    try:
        return cls()
    except Exception:
        return None


def _fetch_all(queries: list[tuple[str, str]], limit: int,
               run_id: str | None = None, iter_no: int = 0) -> list[Post]:
    by_src: dict[str, list[str]] = {}
    for q, src in queries:
        if src not in SOURCES:
            continue
        by_src.setdefault(src, []).append(q)

    posts: list[Post] = []
    serial_calls: list[tuple[Connector, str]] = []
    for src, qs in by_src.items():
        conn = _build_connector(src, run_id, iter_no)
        if conn is None:
            continue
        if getattr(conn, "supports_batch", False) and hasattr(conn, "fetch_many"):
            try:
                posts.extend(conn.fetch_many(qs, limit))
            except Exception:
                pass
        else:
            for q in qs:
                serial_calls.append((conn, q))

    if serial_calls:
        with ThreadPoolExecutor(max_workers=min(12, len(serial_calls))) as ex:
            futures = [ex.submit(c.fetch, q, limit) for c, q in serial_calls]
            for f in futures:
                try:
                    posts.extend(f.result())
                except Exception:
                    continue
    return posts


def run_agent(topic: str, sources: list[str], run_id: str | None = None,
              opinion: str | None = None, close_bus: bool = True) -> str:
    run_id = run_id or new_run_id()
    sources = [s for s in sources if s in SOURCES] or ["facebook"]
    core = extract_core_subject(topic) or topic
    started_at = int(time.time())
    BUS.publish(run_id, {"type": "started", "run_id": run_id, "topic": topic, "sources": sources})

    seen: dict[str, Post] = {}
    queries_log: list[dict] = []
    last_H = 0.0
    stop_reason = "budget"

    seeds = _llm_seed(topic, opinion)
    BUS.publish(run_id, {"type": "seeded", "queries": seeds})
    pending = [(q, s) for q in seeds for s in sources]
    cluster_meta: list[dict] = []
    final_posts: list[Post] = []
    final_members: dict[int, list[Post]] = {}
    prev_cents: dict = {}
    fetched: set[tuple[str, str]] = set()

    for it in range(MAX_ITERS):
        pending = [qs for qs in pending if qs not in fetched]
        if not pending:
            stop_reason = "exhausted"
            break
        BUS.publish(run_id, {"type": "iter_start", "iter": it + 1, "queries": pending})
        per = max(5, MAX_POSTS // max(len(pending), 1))
        new_posts = _fetch_all(pending, limit=per,
                                run_id=run_id, iter_no=it + 1)
        fetched.update(pending)
        added = 0
        new_ids: list[str] = []
        for p in new_posts:
            if p.id not in seen and len(seen) < MAX_POSTS:
                seen[p.id] = p
                new_ids.append(p.id)
                added += 1
        BUS.publish(run_id, {"type": "posts_fetched", "n_new": added, "n_total": len(seen)})
        for q, s in pending:
            queries_log.append({"q": q, "source": s, "iter": it + 1})

        if len(seen) < 6:
            BUS.publish(run_id, {"type": "low_recall", "n": len(seen)})
            pending = [(topic, s) for s in sources]
            continue

        posts = list(seen.values())
        keep_idx = near_dupe_keep([p.text for p in posts])
        if len(keep_idx) < len(posts):
            BUS.publish(run_id, {
                "type": "deduped",
                "kept": len(keep_idx),
                "dropped": len(posts) - len(keep_idx),
            })
            posts = [posts[i] for i in keep_idx]

        on_topic = [p for p in posts
                    if token_overlap_relevance(core, p.text) >= REL_FLOOR]
        if len(on_topic) >= MIN_ONTOPIC and len(on_topic) < len(posts):
            BUS.publish(run_id, {
                "type": "relevance_gated",
                "kept": len(on_topic),
                "dropped": len(posts) - len(on_topic),
            })
            posts = on_topic

        try:
            emb = embed_texts([p.text for p in posts])
        except Exception as e:
            BUS.publish(run_id, {"type": "embed_error", "err": str(e)})
            stop_reason = "embed_error"
            break

        labels = cluster_embeddings(emb)
        H = entropy(labels)
        BUS.publish(run_id, {
            "type": "clustered",
            "k": int(len({int(x) for x in labels if x >= 0})),
            "entropy": H,
        })

        cents = centroids(emb, labels)
        id_to_row = {p.id: i for i, p in enumerate(posts)}
        new_rows = [id_to_row[i] for i in new_ids if i in id_to_row]
        sat = saturation(emb[new_rows], prev_cents) if new_rows else 0.0
        prev_cents = cents
        if sat:
            BUS.publish(run_id, {"type": "saturation", "value": sat})

        cids = sorted(cents.keys())
        members_by_cid = {
            cid: [posts[i] for i, lab in enumerate(labels) if lab == cid]
            for cid in cids
        }

        def _label(cid: int) -> dict:
            try:
                return label_cluster([m.text for m in members_by_cid[cid][:8]])
            except Exception as e:
                return {"label": f"cluster {cid}", "desc": f"label_error: {e}"}

        metas: dict[int, dict] = {}
        if cids:
            with ThreadPoolExecutor(max_workers=min(8, len(cids))) as ex:
                metas = dict(zip(cids, ex.map(_label, cids)))

        # Stance (an LLM call per cluster) is only needed for the final output,
        # not for loop decisions, so it is deferred to the post-loop finalize
        # pass alongside the rerank — keeping per-iteration cost down.
        sentiments: dict[int, dict] = {}

        # Cheap relevance ranking inside the loop keeps the live UI responsive;
        # the expensive LLM rerank runs once after the loop (see _finalize_rerank).
        cluster_meta = []
        for cid in cids:
            members = members_by_cid[cid]
            meta = metas[cid]
            tops = rank_posts(topic, members, n=5)
            cluster_meta.append({
                "id": int(cid),
                "label": meta.get("label", f"cluster {cid}"),
                "desc": meta.get("desc", ""),
                "centroid": cents[cid].tolist(),
                "members": [m.id for m in members],
                "sentiment": sentiments.get(cid, {"pos": 0.0, "neu": 1.0, "neg": 0.0}),
                "top_posts": [m.id for m in tops],
            })
        final_posts = posts
        final_members = members_by_cid

        write_json(run_id, "posts.json", [p.to_dict() for p in posts])
        write_json(run_id, "clusters.json", cluster_meta)
        BUS.publish(run_id, {
            "type": "labeled",
            "clusters": [
                {"id": c["id"], "label": c["label"], "n": len(c["members"]), "sentiment": c["sentiment"]}
                for c in cluster_meta
            ],
        })

        if len(seen) >= MAX_POSTS:
            stop_reason = "budget"
            break
        if it >= MAX_ITERS - 1:
            stop_reason = "iters"
            break
        if abs(H - last_H) < EPS and it > 0:
            stop_reason = "converged"
            break
        if sat >= SAT_EPS and it > 0:
            stop_reason = "saturated"
            break
        last_H = H

        decision = _llm_next(topic, [c["label"] for c in cluster_meta], opinion)
        if decision.get("action") == "stop":
            stop_reason = "agent_stop"
            break
        next_q = [str(q) for q in decision.get("queries", []) if q]
        anchored = [q for q in next_q
                    if token_overlap_relevance(core, q) >= EXPAND_REL_FLOOR]
        next_q = (anchored or next_q)[:3]
        if not next_q:
            stop_reason = "no_queries"
            break
        pending = [(q, s) for q in next_q for s in sources]

    # Single LLM rerank pass on the final corpus — kept out of the loop so the
    # per-iteration cost stays low. Refines top_posts and emits ranked.json.
    if cluster_meta:
        shortlist = rank_posts(topic, final_posts, n=RERANK_SHORTLIST)
        ranked_global = llm_rerank(topic, shortlist, n=len(shortlist))
        rank_index = {p.id: i for i, p in enumerate(ranked_global)}
        try:
            sentiments = cluster_sentiments({
                c["id"]: (c["label"], [m.text for m in final_members.get(c["id"], [])])
                for c in cluster_meta
            })
        except Exception as e:
            sentiments = {c["id"]: {"pos": 0.0, "neu": 1.0, "neg": 0.0, "error": str(e)}
                          for c in cluster_meta}
        for c in cluster_meta:
            members = final_members.get(c["id"], [])
            in_short = sorted((m for m in members if m.id in rank_index),
                              key=lambda m: rank_index[m.id])
            if len(in_short) >= 5:
                tops = in_short[:5]
            else:
                rest = rank_posts(topic, [m for m in members if m.id not in rank_index], n=5)
                tops = (in_short + rest)[:5]
            c["top_posts"] = [m.id for m in tops]
            c["sentiment"] = sentiments.get(c["id"], c["sentiment"])
        write_json(run_id, "clusters.json", cluster_meta)
        write_json(run_id, "ranked.json", [p.to_dict() for p in ranked_global[:15]])
        BUS.publish(run_id, {"type": "reranked", "n": len(ranked_global)})

    write_json(run_id, "run.json", {
        "id": run_id,
        "topic": topic,
        "sources": sources,
        "started_at": started_at,
        "finished_at": int(time.time()),
        "queries": queries_log,
        "stop_reason": stop_reason,
        "metrics": {"posts": len(seen), "clusters": len(cluster_meta)},
    })
    try:
        from .briefing import build as build_briefing
        briefing = build_briefing(run_id, with_pdf=True, exec_summary=True)
        BUS.publish(run_id, {
            "type": "briefing_ready",
            "html": f"/run/{run_id}/briefing/html",
            "pdf": f"/run/{run_id}/briefing/pdf" if briefing["pdf"] else None,
        })
    except Exception as e:
        BUS.publish(run_id, {"type": "briefing_error", "err": str(e)})
    try:
        build_evidence(run_id, opinion)
        BUS.publish(run_id, {"type": "evidence_ready",
                             "url": f"/run/{run_id}/evidence"})
    except Exception as e:
        BUS.publish(run_id, {"type": "evidence_error", "err": str(e)})
    BUS.publish(run_id, {
        "type": "done", "run_id": run_id, "stop_reason": stop_reason, "n_posts": len(seen),
    })
    # When wrapped by the orchestration graph the caller keeps the SSE stream
    # open for its own score/alert/done events and closes it itself.
    if close_bus:
        BUS.close(run_id)
    return run_id
