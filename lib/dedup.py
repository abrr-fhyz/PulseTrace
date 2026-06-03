"""SimHash near-duplicate detection to prune FB-OCR floods before embedding."""
from __future__ import annotations
import hashlib
import re

import numpy as np

_BITS = 64
_TOKEN = re.compile(r"\w+")
_BIT_RANGE = np.arange(_BITS, dtype=np.uint64)


def _shingles(text: str, n: int = 2) -> list[str]:
    words = _TOKEN.findall(text.lower())
    if len(words) < n:
        return words
    return [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]


def _token_hash(token: str) -> int:
    return int.from_bytes(hashlib.md5(token.encode("utf-8")).digest()[:8], "big")


def simhash(text: str, bits: int = _BITS) -> int:
    toks = _shingles(text)
    if not toks:
        return 0
    hs = np.fromiter((_token_hash(t) for t in toks), dtype=np.uint64, count=len(toks))
    bit_set = (hs[:, None] >> _BIT_RANGE[:bits]) & np.uint64(1)
    acc = bit_set.sum(axis=0).astype(np.int64) * 2 - len(toks)
    out = 0
    for b in range(bits):
        if acc[b] > 0:
            out |= 1 << b
    return out


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def near_dupe_keep(texts: list[str], threshold: int = 10) -> list[int]:
    """Return indices of texts to keep, dropping near-dupes of earlier kept ones."""
    kept: list[int] = []
    kept_hashes: list[int] = []
    for i, t in enumerate(texts):
        h = simhash(t)
        if any(hamming(h, kh) <= threshold for kh in kept_hashes):
            continue
        kept.append(i)
        kept_hashes.append(h)
    return kept
