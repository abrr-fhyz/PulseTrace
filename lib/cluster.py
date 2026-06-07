"""Cluster normalized embeddings. HDBSCAN primary, KMeans fallback."""
from __future__ import annotations
import numpy as np


def cluster_embeddings(emb: np.ndarray, min_cluster_size: int = 4) -> np.ndarray:
    n = len(emb)
    if n < min_cluster_size * 2:
        return np.zeros(n, dtype=int)
    try:
        import hdbscan
        labels = hdbscan.HDBSCAN(
            min_cluster_size=min_cluster_size, metric="euclidean"
        ).fit_predict(emb)
        if (labels >= 0).sum() >= min_cluster_size:
            return labels.astype(int)
    except Exception:
        pass
    from sklearn.cluster import KMeans
    k = max(2, round((n / 2) ** 0.5))
    return KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(emb).astype(int)


def centroids(emb: np.ndarray, labels: np.ndarray) -> dict[int, np.ndarray]:
    out: dict[int, np.ndarray] = {}
    for c in {int(x) for x in labels}:
        if c < 0:
            continue
        mask = labels == c
        v = emb[mask].mean(axis=0)
        nrm = float(np.linalg.norm(v))
        out[c] = (v / max(nrm, 1e-9)).astype(np.float32)
    return out


def saturation(new_emb: np.ndarray, cents: dict[int, np.ndarray]) -> float:
    """Mean over new posts of their max cosine to any existing centroid.

    Inputs are unit-normalized, so cosine == dot. ~1.0 => the corpus is
    saturating (new posts land on top of known clusters); ~0.0 => fresh ground.
    """
    if not cents or len(new_emb) == 0:
        return 0.0
    cmat = np.stack([cents[c] for c in cents])
    sims = new_emb @ cmat.T
    return float(sims.max(axis=1).mean())


def entropy(labels: np.ndarray) -> float:
    valid = labels[labels >= 0]
    if len(valid) == 0:
        return 0.0
    counts = np.bincount(valid)
    p = counts / counts.sum()
    return float(-(p * np.log(p + 1e-12)).sum())
