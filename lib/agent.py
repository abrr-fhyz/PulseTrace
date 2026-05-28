"""Agent loop: seed queries -> fetch -> cluster -> label -> expand or stop."""
from __future__ import annotations
import time
from concurrent.futures import ThreadPoolExecutor
from .connectors.base import Connector, Post
from .connectors.reddit import RedditConnector
from .connectors.hn import HNConnector
from .embed import embed_texts
from .cluster import cluster_embeddings, centroids, entropy
from .label import label_cluster
from .stance import cluster_sentiment
from .influence import top_n
from .events import BUS
from .store import write_json, new_run_id
from .llm import chat_json


MAX_ITERS = 4
MAX_POSTS = 500
EPS = 0.05
SOURCES: dict[str, type[Connector]] = {"reddit": RedditConnector, "hn": HNConnector}


SEED_SYS = (
    "Generate 5 diverse, complementary search queries for social-media research "
    'on the user\'s topic. Output JSON: {"queries": ["..."]}'
)
NEXT_SYS = (
    "Given cluster labels found so far and the topic, decide: stop or expand. "
    "If expand, propose up to 3 new search queries targeting under-covered angles. "
    'Output JSON: {"action": "stop"|"expand", "queries": ["..."]}'
)


def _llm_seed(topic: str) -> list[str]:
    try:
        out = chat_json(SEED_SYS, f"Topic: {topic}")
    except Exception:
        return [topic]
    qs = [str(q) for q in out.get("queries", []) if q]
    return qs[:5] or [topic]


def _llm_next(topic: str, labels: list[str]) -> dict:
    try:
        return chat_json(NEXT_SYS, f"Topic: {topic}\nLabels so far:\n- " + "\n- ".join(labels))
    except Exception:
        return {"action": "stop", "queries": []}


def _fetch_all(queries: list[tuple[str, str]], limit: int) -> list[Post]:
    posts: list[Post] = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = []
        for q, src in queries:
            if src not in SOURCES:
                continue
            try:
                conn = SOURCES[src]()
            except Exception:
                continue
            futures.append(ex.submit(conn.fetch, q, limit))
        for f in futures:
            try:
                posts.extend(f.result())
            except Exception:
                continue
    return posts


def run_agent(topic: str, sources: list[str]) -> str:
    run_id = new_run_id()
    sources = [s for s in sources if s in SOURCES] or ["hn"]
    BUS.publish(run_id, {"type": "started", "run_id": run_id, "topic": topic, "sources": sources})

    seen: dict[str, Post] = {}
    queries_log: list[dict] = []
    last_H = 0.0
    stop_reason = "budget"

    seeds = _llm_seed(topic)
    BUS.publish(run_id, {"type": "seeded", "queries": seeds})
    pending = [(q, s) for q in seeds for s in sources]
    cluster_meta: list[dict] = []

    for it in range(MAX_ITERS):
        BUS.publish(run_id, {"type": "iter_start", "iter": it + 1, "queries": pending})
        per = max(5, MAX_POSTS // max(len(pending), 1))
        new_posts = _fetch_all(pending, limit=per)
        added = 0
        for p in new_posts:
            if p.id not in seen and len(seen) < MAX_POSTS:
                seen[p.id] = p
                added += 1
        BUS.publish(run_id, {"type": "posts_fetched", "n_new": added, "n_total": len(seen)})
        for q, s in pending:
            queries_log.append({"q": q, "source": s, "iter": it + 1})

        if len(seen) < 6:
            BUS.publish(run_id, {"type": "low_recall", "n": len(seen)})
            pending = [(topic, s) for s in sources]
            continue

        posts = list(seen.values())
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
        cluster_meta = []
        for cid in sorted(cents.keys()):
            members = [posts[i] for i, lab in enumerate(labels) if lab == cid]
            sample = [m.text for m in members[:8]]
            meta = label_cluster(sample)
            sent = cluster_sentiment(meta["label"], [m.text for m in members])
            tops = top_n(members, n=5)
            cluster_meta.append({
                "id": int(cid),
                "label": meta["label"],
                "desc": meta["desc"],
                "centroid": cents[cid].tolist(),
                "members": [m.id for m in members],
                "sentiment": sent,
                "top_posts": [m.id for m in tops],
            })

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
        last_H = H

        decision = _llm_next(topic, [c["label"] for c in cluster_meta])
        if decision.get("action") == "stop":
            stop_reason = "agent_stop"
            break
        next_q = [str(q) for q in decision.get("queries", []) if q][:3]
        if not next_q:
            stop_reason = "no_queries"
            break
        pending = [(q, s) for q in next_q for s in sources]

    write_json(run_id, "run.json", {
        "id": run_id,
        "topic": topic,
        "sources": sources,
        "started_at": int(time.time()),
        "queries": queries_log,
        "stop_reason": stop_reason,
        "metrics": {"posts": len(seen), "clusters": len(cluster_meta)},
    })
    BUS.publish(run_id, {
        "type": "done", "run_id": run_id, "stop_reason": stop_reason, "n_posts": len(seen),
    })
    BUS.close(run_id)
    return run_id
