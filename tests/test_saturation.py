import numpy as np
from lib.cluster import saturation


def _cents(*vecs):
    return {i: np.asarray(v, dtype=np.float32) for i, v in enumerate(vecs)}


def test_no_centroids_is_zero():
    new = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    assert saturation(new, {}) == 0.0


def test_no_new_posts_is_zero():
    cents = _cents([1.0, 0.0])
    assert saturation(np.zeros((0, 2), dtype=np.float32), cents) == 0.0


def test_identical_to_centroid_is_one():
    cents = _cents([1.0, 0.0], [0.0, 1.0])
    new = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    assert saturation(new, cents) == 1.0


def test_orthogonal_new_posts_low():
    cents = _cents([1.0, 0.0])
    new = np.array([[0.0, 1.0], [0.0, 1.0]], dtype=np.float32)
    assert saturation(new, cents) < 0.1


def test_uses_max_over_centroids_then_means():
    cents = _cents([1.0, 0.0], [0.0, 1.0])
    # first new post hugs centroid 0, second sits at 45deg (~0.707 to each)
    new = np.array([[1.0, 0.0], [0.70710678, 0.70710678]], dtype=np.float32)
    val = saturation(new, cents)
    assert abs(val - (1.0 + 0.70710678) / 2) < 1e-4
