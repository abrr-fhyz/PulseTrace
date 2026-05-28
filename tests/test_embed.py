from lib.embed import _key, embed_texts
import numpy as np


def test_key_deterministic():
    assert _key("hello") == _key("hello")
    assert _key("a") != _key("b")


def test_embed_empty():
    arr = embed_texts([])
    assert arr.shape == (0, 1536)
    assert arr.dtype == np.float32
