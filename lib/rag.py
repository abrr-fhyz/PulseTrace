"""FAISS-backed RAG over a run's posts."""
from __future__ import annotations
import json
import numpy as np
import faiss
from .embed import embed_texts
from .llm import chat_json
from .store import run_dir


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
        out = chat_json(ASK_SYS, f"Question: {question}\n\nPosts:\n{context}")
    except Exception as e:
        return {"answer": f"LLM error: {e}", "citations": [], "retrieved": hits}
    return {
        "answer": str(out.get("answer", "")),
        "citations": [str(c) for c in out.get("citations", [])],
        "retrieved": hits,
    }
