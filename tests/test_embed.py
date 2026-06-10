import numpy as np

import lib.embed as embed
from lib.embed import _key, _load_cached, _peek_key, embed_texts


def test_key_deterministic():
    assert _key("hello") == _key("hello")
    assert _key("a") != _key("b")


def test_embed_empty():
    arr = embed_texts([])
    assert arr.shape == (0, 3072)
    assert arr.dtype == np.float32


def test_peek_key_matches_writer_format():
    k = _key("anything")
    line = '{"k": "%s", "v": [0.1, 0.2, 0.3]}' % k
    assert _peek_key(line) == k


def test_peek_key_rejects_non_matching():
    assert _peek_key('{"note": "no key here"}') is None


def test_load_cached_only_returns_wanted(tmp_path, monkeypatch):
    cache_file = tmp_path / "embed_cache.jsonl"
    monkeypatch.setattr(embed, "CACHE_PATH", cache_file)
    embed._append_cache([("a" * 40, [1.0]), ("b" * 40, [2.0]), ("c" * 40, [3.0])])

    got = _load_cached({"a" * 40, "c" * 40})
    assert set(got) == {"a" * 40, "c" * 40}
    assert got["a" * 40] == [1.0]


def test_embed_cache_hit_skips_provider(tmp_path, monkeypatch):
    cache_file = tmp_path / "embed_cache.jsonl"
    gemini = embed.backend.PROVIDERS["gemini"]
    monkeypatch.setattr(embed, "CACHE_PATH", cache_file)
    monkeypatch.setattr(embed.backend, "is_ollama", lambda: False)
    monkeypatch.setattr(embed.backend, "embed_provider", lambda: gemini)

    calls: list[list[str]] = []

    def fake_provider_embed(_provider, texts, _batch):
        calls.append(list(texts))
        return [[float(len(t)), 1.0, 2.0] for t in texts]

    monkeypatch.setattr(embed, "_embed_openai_compat", fake_provider_embed)

    first = embed_texts(["hello", "world"])
    assert first.shape == (2, 3)
    assert len(calls) == 1 and calls[0] == ["hello", "world"]

    embed_texts(["hello", "world"])
    assert len(calls) == 1  # second call served entirely from cache


def test_embed_dedupes_identical_texts_in_batch(tmp_path, monkeypatch):
    cache_file = tmp_path / "embed_cache.jsonl"
    gemini = embed.backend.PROVIDERS["gemini"]
    monkeypatch.setattr(embed, "CACHE_PATH", cache_file)
    monkeypatch.setattr(embed.backend, "is_ollama", lambda: False)
    monkeypatch.setattr(embed.backend, "embed_provider", lambda: gemini)

    sent: list[list[str]] = []

    def fake_provider_embed(_provider, texts, _batch):
        sent.append(list(texts))
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(embed, "_embed_openai_compat", fake_provider_embed)

    arr = embed_texts(["dup", "dup", "dup"])
    assert arr.shape == (3, 2)
    assert sent == [["dup"]]  # provider asked once, not three times
