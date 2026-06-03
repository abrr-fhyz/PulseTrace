"""Per-cluster word clouds via TF-IDF over cluster-level documents."""
from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer

_TOKEN_PATTERN = r"(?u)\b[a-zA-Z]{3,}\b"


def _top_from_row(vocab: list[str], row, top_k: int) -> list[tuple[str, float]]:
    weights = row.toarray().ravel()
    ranked = sorted(
        ((vocab[i], float(w)) for i, w in enumerate(weights) if w > 0),
        key=lambda kv: kv[1],
        reverse=True,
    )
    return ranked[:top_k]


def cluster_terms(texts: list[str], top_k: int = 15) -> list[tuple[str, float]]:
    doc = " ".join(t for t in texts if t and t.strip())
    if not doc.strip():
        return []
    vec = TfidfVectorizer(
        stop_words="english",
        lowercase=True,
        token_pattern=_TOKEN_PATTERN,
    )
    try:
        matrix = vec.fit_transform([doc])
    except ValueError:
        return []
    return _top_from_row(vec.get_feature_names_out().tolist(), matrix[0], top_k)


def run_wordclouds(
    clusters: list[dict],
    posts_by_id: dict[str, dict],
    top_k: int = 15,
) -> dict[int, list[tuple[str, float]]]:
    if not clusters:
        return {}

    docs: list[str] = []
    for c in clusters:
        texts = [
            (posts_by_id.get(mid) or {}).get("text", "")
            for mid in c.get("members", [])
        ]
        docs.append(" ".join(t for t in texts if t and t.strip()))

    if not any(d.strip() for d in docs):
        return {c["id"]: [] for c in clusters}

    vec = TfidfVectorizer(
        stop_words="english",
        lowercase=True,
        token_pattern=_TOKEN_PATTERN,
    )
    try:
        matrix = vec.fit_transform(docs)
    except ValueError:
        return {c["id"]: [] for c in clusters}

    vocab = vec.get_feature_names_out().tolist()
    out: dict[int, list[tuple[str, float]]] = {}
    for i, c in enumerate(clusters):
        if not docs[i].strip():
            out[c["id"]] = []
        else:
            out[c["id"]] = _top_from_row(vocab, matrix[i], top_k)
    return out
