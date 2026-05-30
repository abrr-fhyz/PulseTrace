"""LLM-named cluster labels from sample post texts."""
from __future__ import annotations
from .llm import chat_json


SYS = (
    "You name clusters of social posts. Output strict JSON: "
    '{"label": "<=6 words", "desc": "1-2 sentences"}'
)


def label_cluster(samples: list[str]) -> dict:
    if not samples:
        return {"label": "Empty", "desc": ""}
    body = "\n\n---\n\n".join(s[:500] for s in samples[:8])
    try:
        out = chat_json(SYS, f"Posts in this cluster:\n{body}", stage="label")
    except Exception:
        return {"label": "Unlabeled", "desc": ""}
    return {
        "label": str(out.get("label", "Unlabeled"))[:80],
        "desc": str(out.get("desc", ""))[:300],
    }
