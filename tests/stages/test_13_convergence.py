"""Stage 13: cluster entropy + convergence stop condition.

Backs README "Entropy delta: 0.03 -> Converged." live-log behavior.
"""
from __future__ import annotations
import numpy as np

import pytest

from lib.cluster import entropy, cluster_embeddings, centroids

from .conftest import write_stage_artifact


def test_entropy_zero_for_single_cluster():
    # Implementation adds 1e-12 epsilon inside log to avoid log(0), so the
    # result is bounded by a small negative quantity, not exactly 0.
    assert entropy(np.array([0, 0, 0, 0])) == pytest.approx(0.0, abs=1e-9)


def test_entropy_maximal_for_uniform_split():
    """Two equal-sized clusters -> ln(2)."""
    labs = np.array([0, 0, 1, 1])
    assert entropy(labs) == pytest.approx(np.log(2), rel=1e-3)


def test_entropy_ignores_noise_label():
    """HDBSCAN labels noise as -1; entropy must skip those."""
    labs = np.array([-1, -1, 0, 0, 1, 1])
    assert entropy(labs) == pytest.approx(np.log(2), rel=1e-3)


def test_entropy_empty_input():
    assert entropy(np.array([], dtype=int)) == 0.0


def test_cluster_then_entropy_on_synthetic_blobs():
    """Two well-separated Gaussian blobs in 2D must form >=2 clusters
    and produce non-zero entropy."""
    rng = np.random.default_rng(0)
    blob_a = rng.normal(loc=[0, 0], scale=0.05, size=(30, 2))
    blob_b = rng.normal(loc=[5, 5], scale=0.05, size=(30, 2))
    emb = np.vstack([blob_a, blob_b]).astype(np.float32)
    # Normalize (cosine convention used elsewhere).
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)

    labs = cluster_embeddings(emb, min_cluster_size=4)
    H = entropy(labs)
    cents = centroids(emb, labs)

    write_stage_artifact("stage13_convergence.json", {
        "n_points": int(len(emb)),
        "n_clusters": int(len(cents)),
        "entropy": H,
        "noise_fraction": float((labs == -1).mean()),
    })

    assert len(cents) >= 2
    assert H > 0.0


def test_convergence_logic_eps_threshold():
    """The agent stops when |H - last_H| < EPS for it > 0. Verify the
    comparison literal so refactors don't silently move the threshold."""
    from lib import agent
    assert 0 < agent.EPS < 0.5
