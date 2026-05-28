import numpy as np
from lib.cluster import entropy


def test_uniform_higher_entropy_than_skewed():
    uniform = np.array([0, 1, 2, 0, 1, 2])
    skewed = np.array([0, 0, 0, 0, 0, 1])
    assert entropy(uniform) > entropy(skewed)


def test_entropy_all_noise_is_zero():
    assert entropy(np.array([-1, -1, -1])) == 0.0
