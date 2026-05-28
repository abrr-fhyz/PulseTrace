import numpy as np
from lib.cluster import cluster_embeddings, centroids, entropy


def test_cluster_two_blobs():
    rng = np.random.default_rng(0)
    a = rng.normal(loc=+1.0, size=(20, 8)).astype(np.float32)
    b = rng.normal(loc=-1.0, size=(20, 8)).astype(np.float32)
    x = np.vstack([a, b])
    x = x / np.linalg.norm(x, axis=1, keepdims=True)
    labels = cluster_embeddings(x, min_cluster_size=4)
    valid = labels[labels >= 0]
    assert len(set(valid.tolist())) >= 2


def test_centroids_and_entropy():
    x = np.eye(6, dtype=np.float32)
    labels = np.array([0, 0, 1, 1, 2, 2])
    c = centroids(x, labels)
    assert set(c.keys()) == {0, 1, 2}
    assert entropy(labels) > 1.0


def test_entropy_uniform_higher_than_skewed():
    uniform = np.array([0, 1, 2, 0, 1, 2])
    skewed = np.array([0, 0, 0, 0, 0, 1])
    assert entropy(uniform) > entropy(skewed)
