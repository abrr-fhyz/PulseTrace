"""Streaming orchestration for the chat workspace.

Runs the same self-reflective RAG loop as lib.rag.ask but yields stage events so
the UI can show honest progress (retrieving -> drafting -> verifying -> refining)
over SSE. The final answer arrives whole (strict-JSON); the client animates it.
"""
from __future__ import annotations

from collections.abc import Iterator

from .llm import chat_json
from .retrieve import hybrid_search
from .rag import (
    ASK_SYS, JUDGE_SYS, REFINE_SYS, REFLECT_THRESHOLD, MAX_REFLECT_ITERS,
    _ensure_index, _load_posts_dict, _citation_detail, _ask_user_msg,
)


def answer_stream(run_id: str, question: str, *, preamble: str = "",
                  k: int = 8) -> Iterator[dict]:
    if not _ensure_index(run_id):
        yield {"type": "answer", "answer": "No data for this run.",
               "citations_detail": [], "confidence": 0.0, "iterations": 0}
        yield {"type": "done"}
        return

    posts = _load_posts_dict(run_id)
    query = question
    best: dict | None = None
    best_conf = -1.0
    iters = 0

    while iters < MAX_REFLECT_ITERS:
        iters += 1
        yield {"stage": "retrieving"}
        hits = hybrid_search(run_id, query, k)
        yield {"stage": "retrieved", "n": len([h for h in hits if h in posts])}

        context = "\n\n".join(
            f"[{pid}] {posts[pid]['text'][:600]}" for pid in hits if pid in posts
        )

        yield {"stage": "drafting"}
        try:
            out = chat_json(ASK_SYS, _ask_user_msg(question, context, preamble),
                            stage="rag")
        except Exception as e:
            yield {"type": "answer", "answer": f"LLM error: {e}",
                   "citations_detail": [], "confidence": 0.0, "iterations": iters}
            yield {"type": "done"}
            return

        raw_cites = [str(c) for c in out.get("citations", [])]
        answer = {
            "answer": str(out.get("answer", "")),
            "citations_detail": [_citation_detail(run_id, c, posts) for c in raw_cites],
        }

        yield {"stage": "verifying"}
        try:
            verdict = chat_json(
                JUDGE_SYS,
                f"Question: {question}\n\nAnswer: {answer['answer']}\n\nPosts:\n{context}",
                stage="rag_judge")
            conf = float(verdict.get("confidence", 1.0))
            gap = str(verdict.get("gap", ""))
        except Exception:
            answer["confidence"] = 1.0
            answer["iterations"] = iters
            yield {"type": "answer", **answer}
            yield {"type": "done"}
            return

        yield {"stage": "verified", "confidence": conf}
        if conf > best_conf:
            best, best_conf = answer, conf

        if conf >= REFLECT_THRESHOLD or iters >= MAX_REFLECT_ITERS:
            break

        yield {"stage": "refining"}
        try:
            refined = chat_json(REFINE_SYS,
                                f"Original question: {question}\nGap: {gap}",
                                stage="rag_refine")
            query = str(refined.get("query", query)) or query
        except Exception:
            break

    final = dict(best or {"answer": "", "citations_detail": []})
    final["confidence"] = best_conf if best_conf >= 0 else 0.0
    final["iterations"] = iters
    yield {"type": "answer", **final}
    yield {"type": "done"}
