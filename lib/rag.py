"""FAISS-backed RAG over a run's posts."""
from __future__ import annotations
import json
import numpy as np
import faiss
from .embed import embed_texts
from .llm import chat_json
from .store import run_dir


def _normalize_cite(raw: str, posts: dict) -> str | None:
    """LLM often strips the 'facebook:' prefix. Try several keys."""
    if not raw:
        return None
    s = str(raw).strip().lstrip("[").rstrip("]")
    if s in posts:
        return s
    for pid in posts:
        if pid.endswith(":" + s) or pid.endswith(s):
            return pid
    return None


def _resolve_shot_url(run_id: str, shot_name: str) -> str | None:
    if not shot_name:
        return None
    shots_root = run_dir(run_id) / "shots"
    if not shots_root.exists():
        return None
    for it_dir in shots_root.iterdir():
        if not it_dir.is_dir():
            continue
        if (it_dir / shot_name).exists():
            return f"/shots/{run_id}/{it_dir.name}/{shot_name}"
    return None


def _citation_detail(run_id: str, cite_raw: str, posts: dict) -> dict:
    pid = _normalize_cite(cite_raw, posts)
    if pid is None:
        return {"raw": str(cite_raw), "resolved": False,
                "label": str(cite_raw)}
    post = posts[pid]
    raw = post.get("raw") or {}
    shot_name = raw.get("shot") if isinstance(raw, dict) else None
    shot_url = _resolve_shot_url(run_id, shot_name) if shot_name else None
    short = pid.split(":", 1)[-1]
    return {
        "raw": str(cite_raw),
        "resolved": True,
        "id": pid,
        "label": short[-9:] if len(short) > 12 else short,
        "source": post.get("source"),
        "author": post.get("author"),
        "url": post.get("url"),
        "text_preview": (post.get("text") or "")[:240],
        "shot_url": shot_url,
        "query": raw.get("query") if isinstance(raw, dict) else None,
    }


def build_index(run_id: str) -> None:
    posts_path = run_dir(run_id) / "posts.json"
    if not posts_path.exists():
        return
    posts = json.loads(posts_path.read_text())
    texts = [p["text"] for p in posts]
    if not texts:
        return
    emb = embed_texts(texts).astype(np.float32)
    idx = faiss.IndexFlatIP(emb.shape[1])
    idx.add(emb)
    faiss.write_index(idx, str(run_dir(run_id) / "index.faiss"))
    (run_dir(run_id) / "ids.json").write_text(json.dumps([p["id"] for p in posts]))


ASK_SYS = (
    "Answer the user's question using ONLY the provided posts as evidence. "
    "Cite post ids in square brackets like [id]. If unknown, say so. "
    'Output JSON: {"answer": "...", "citations": ["id", ...]}'
)


def ask(run_id: str, question: str, k: int = 8) -> dict:
    d = run_dir(run_id)
    idx_path = d / "index.faiss"
    if not idx_path.exists():
        build_index(run_id)
    if not idx_path.exists():
        return {"answer": "No data for this run.", "citations": [], "retrieved": []}

    idx = faiss.read_index(str(idx_path))
    ids = json.loads((d / "ids.json").read_text())
    posts = {p["id"]: p for p in json.loads((d / "posts.json").read_text())}

    qvec = embed_texts([question]).astype(np.float32)
    _, I = idx.search(qvec, k)
    hits = [ids[i] for i in I[0] if 0 <= i < len(ids)]
    context = "\n\n".join(
        f"[{pid}] {posts[pid]['text'][:600]}" for pid in hits if pid in posts
    )
    try:
        out = chat_json(ASK_SYS, f"Question: {question}\n\nPosts:\n{context}", stage="rag")
    except Exception as e:
        return {"answer": f"LLM error: {e}", "citations": [], "retrieved": hits}
    raw_cites = [str(c) for c in out.get("citations", [])]
    cites_detail = [_citation_detail(run_id, c, posts) for c in raw_cites]
    return {
        "answer": str(out.get("answer", "")),
        "citations": raw_cites,
        "citations_detail": cites_detail,
        "retrieved": hits,
    }
