"""FAISS-backed RAG over a run's posts: hybrid retrieval + self-reflective loop."""
from __future__ import annotations
import json
import numpy as np
import faiss
from .embed import embed_texts
from .llm import chat_json
from .retrieve import hybrid_search
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

JUDGE_SYS = (
    "You are grading a draft answer against the ONLY evidence available (the posts). "
    "Judge whether every claim in the answer is supported by the posts and whether "
    "the posts cover the question. "
    'Output JSON: {"confidence": 0.0-1.0, "supported": true/false, '
    '"gap": "what evidence is missing or unsupported, empty if none"}'
)

REFINE_SYS = (
    "Rewrite the search query to retrieve evidence that fills the stated gap. "
    "Keep it short and keyword-focused. "
    'Output JSON: {"query": "rewritten query"}'
)

REFLECT_THRESHOLD = 0.6
MAX_REFLECT_ITERS = 2


def _ensure_index(run_id: str) -> bool:
    idx_path = run_dir(run_id) / "index.faiss"
    if not idx_path.exists():
        build_index(run_id)
    return idx_path.exists()


def _load_posts_dict(run_id: str) -> dict:
    return {p["id"]: p for p in json.loads((run_dir(run_id) / "posts.json").read_text())}


def ask(run_id: str, question: str, k: int = 8) -> dict:
    if not _ensure_index(run_id):
        return {"answer": "No data for this run.", "citations": [],
                "citations_detail": [], "retrieved": [], "confidence": 0.0,
                "iterations": 0}

    posts = _load_posts_dict(run_id)
    query = question
    best: dict | None = None
    best_conf = -1.0
    iters = 0

    while iters < MAX_REFLECT_ITERS:
        iters += 1
        hits = hybrid_search(run_id, query, k)
        context = "\n\n".join(
            f"[{pid}] {posts[pid]['text'][:600]}" for pid in hits if pid in posts
        )
        try:
            out = chat_json(ASK_SYS, f"Question: {question}\n\nPosts:\n{context}",
                            stage="rag")
        except Exception as e:
            return {"answer": f"LLM error: {e}", "citations": [],
                    "citations_detail": [], "retrieved": hits,
                    "confidence": 0.0, "iterations": iters}

        raw_cites = [str(c) for c in out.get("citations", [])]
        answer = {
            "answer": str(out.get("answer", "")),
            "citations": raw_cites,
            "citations_detail": [_citation_detail(run_id, c, posts) for c in raw_cites],
            "retrieved": hits,
        }

        try:
            verdict = chat_json(JUDGE_SYS,
                                f"Question: {question}\n\nAnswer: {answer['answer']}\n\n"
                                f"Posts:\n{context}", stage="rag_judge")
            conf = float(verdict.get("confidence", 1.0))
            gap = str(verdict.get("gap", ""))
        except Exception:
            answer["confidence"] = 1.0
            return {**answer, "iterations": iters}

        if conf > best_conf:
            best, best_conf = answer, conf

        if conf >= REFLECT_THRESHOLD or iters >= MAX_REFLECT_ITERS:
            break

        try:
            refined = chat_json(REFINE_SYS,
                                f"Original question: {question}\nGap: {gap}",
                                stage="rag_refine")
            query = str(refined.get("query", query)) or query
        except Exception:
            break

    return {**best, "confidence": best_conf, "iterations": iters}
