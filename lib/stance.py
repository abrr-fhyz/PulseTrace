"""Per-cluster sentiment aggregation via batched LLM."""
from __future__ import annotations
from .llm import chat_json


SYS = (
    "Classify each post's sentiment toward the cluster theme. "
    'Output JSON: {"items": [{"i": <index>, "s": "pos"|"neu"|"neg"}]}'
)


def score_batch(theme: str, texts: list[str]) -> list[str]:
    if not texts:
        return []
    enum = "\n".join(f"[{i}] {t[:400]}" for i, t in enumerate(texts))
    try:
        out = chat_json(SYS, f"Theme: {theme}\nPosts:\n{enum}", max_tokens=600)
    except Exception:
        return ["neu"] * len(texts)
    by_i = {int(it.get("i", -1)): it.get("s", "neu") for it in out.get("items", [])}
    return [by_i.get(i, "neu") for i in range(len(texts))]


def cluster_sentiment(theme: str, texts: list[str], batch: int = 8) -> dict:
    pos = neu = neg = 0
    for start in range(0, len(texts), batch):
        for s in score_batch(theme, texts[start:start + batch]):
            if s == "pos":
                pos += 1
            elif s == "neg":
                neg += 1
            else:
                neu += 1
    total = max(pos + neu + neg, 1)
    return {"pos": pos / total, "neu": neu / total, "neg": neg / total}
