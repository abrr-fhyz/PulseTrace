# Hybrid + Self-Reflective RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace pure-dense RAG with BM25+dense hybrid retrieval (RRF fusion) and a self-reflective answer loop, so `lib/rag.py:ask()` matches the submission claim.

**Architecture:** New `lib/retrieve.py` owns hybrid retrieval (dense FAISS + BM25, merged by Reciprocal Rank Fusion). `lib/rag.py:ask()` orchestrates: retrieve → answer → LLM-judge confidence → refine query + re-retrieve (≤2 iters) → finalize. All external IO mocked in tests; graceful degrade to dense-only if `rank_bm25` missing.

**Tech Stack:** Python 3.12, faiss-cpu (existing), rank_bm25 (new), existing `lib/embed.py` + `lib/llm.py:chat_json`, pytest with mocks.

Spec: `docs/superpowers/specs/2026-06-09-hybrid-self-reflective-rag-design.md`

---

### Task 1: Add rank_bm25 dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add the dep line**

Add after the `faiss-cpu>=1.7.4` line in `requirements.txt`:

```
rank_bm25>=0.2
```

- [ ] **Step 2: Install it**

Run: `.venv/bin/pip install "rank_bm25>=0.2"`
Expected: `Successfully installed rank_bm25-0.2.x`

- [ ] **Step 3: Verify import**

Run: `.venv/bin/python -c "from rank_bm25 import BM25Okapi; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore(rag): add rank_bm25 dependency"
```

---

### Task 2: Pure RRF + tokenizer in lib/retrieve.py

**Files:**
- Create: `lib/retrieve.py`
- Test: `tests/test_retrieve.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_retrieve.py`:

```python
from __future__ import annotations

from lib.retrieve import _tokenize, rrf_merge


def test_tokenize_lowercases_and_splits_on_punct():
    assert _tokenize("Hello, RAG-World! 2026") == ["hello", "rag", "world", "2026"]


def test_tokenize_empty():
    assert _tokenize("") == []


def test_rrf_merge_single_list_preserves_order():
    assert rrf_merge([["a", "b", "c"]]) == ["a", "b", "c"]


def test_rrf_merge_rewards_agreement():
    # "b" is rank 1 in list-1 and rank 0 in list-2 -> highest fused score
    dense = ["a", "b", "c"]
    bm25 = ["b", "d", "a"]
    out = rrf_merge([dense, bm25])
    assert out[0] == "b"
    assert set(out) == {"a", "b", "c", "d"}


def test_rrf_merge_empty():
    assert rrf_merge([]) == []
    assert rrf_merge([[], []]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_retrieve.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.retrieve'`

- [ ] **Step 3: Write minimal implementation**

Create `lib/retrieve.py`:

```python
"""Hybrid retrieval: dense (FAISS) + BM25, merged via Reciprocal Rank Fusion."""
from __future__ import annotations

import re

RRF_K = 60

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def rrf_merge(rankings: list[list[str]], k: int = RRF_K) -> list[str]:
    """Reciprocal Rank Fusion. score(id) = sum 1/(k + rank0) across rankings."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda i: scores[i], reverse=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_retrieve.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add lib/retrieve.py tests/test_retrieve.py
git commit -m "feat(rag): add RRF merge + tokenizer for hybrid retrieval"
```

---

### Task 3: BM25 + dense + hybrid search in lib/retrieve.py

**Files:**
- Modify: `lib/retrieve.py`
- Test: `tests/test_retrieve.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_retrieve.py`:

```python
from lib.retrieve import bm25_search, hybrid_search


def test_bm25_search_ranks_matching_post_first():
    posts = [
        {"id": "p1", "text": "cats are great pets"},
        {"id": "p2", "text": "retrieval augmented generation pipeline"},
        {"id": "p3", "text": "weather is sunny today"},
    ]
    out = bm25_search(posts, "retrieval generation", n=3)
    assert out[0] == "p2"


def test_bm25_search_empty_corpus():
    assert bm25_search([], "anything", n=5) == []


def test_hybrid_search_fuses_dense_and_bm25(monkeypatch):
    import lib.retrieve as R
    monkeypatch.setattr(R, "dense_search", lambda run_id, q, n: ["a", "b", "c"])
    monkeypatch.setattr(R, "_load_posts", lambda run_id: [{"id": "b", "text": "x"}])
    monkeypatch.setattr(R, "bm25_search", lambda posts, q, n: ["b", "d"])
    out = hybrid_search("run1", "q", k=4)
    assert out[0] == "b"  # appears in both -> top


def test_hybrid_search_falls_back_to_dense_when_bm25_unavailable(monkeypatch):
    import lib.retrieve as R
    monkeypatch.setattr(R, "dense_search", lambda run_id, q, n: ["a", "b", "c"])
    monkeypatch.setattr(R, "_load_posts", lambda run_id: [{"id": "a", "text": "x"}])

    def boom(posts, q, n):
        raise RuntimeError("rank_bm25 missing")

    monkeypatch.setattr(R, "bm25_search", boom)
    out = hybrid_search("run1", "q", k=3)
    assert out == ["a", "b", "c"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_retrieve.py -v`
Expected: FAIL with `ImportError: cannot import name 'bm25_search'`

- [ ] **Step 3: Write minimal implementation**

Append to `lib/retrieve.py` (add imports at top with the existing ones):

```python
import json

import numpy as np

from .embed import embed_texts
from .store import run_dir
```

Then append these functions:

```python
def _load_posts(run_id: str) -> list[dict]:
    path = run_dir(run_id) / "posts.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


def dense_search(run_id: str, query: str, n: int) -> list[str]:
    import faiss

    d = run_dir(run_id)
    idx_path = d / "index.faiss"
    if not idx_path.exists():
        return []
    idx = faiss.read_index(str(idx_path))
    ids = json.loads((d / "ids.json").read_text())
    qvec = embed_texts([query]).astype(np.float32)
    _, I = idx.search(qvec, n)
    return [ids[i] for i in I[0] if 0 <= i < len(ids)]


def bm25_search(posts: list[dict], query: str, n: int) -> list[str]:
    if not posts:
        return []
    from rank_bm25 import BM25Okapi

    corpus = [_tokenize(p["text"]) for p in posts]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))
    order = np.argsort(scores)[::-1][:n]
    return [posts[i]["id"] for i in order]


def hybrid_search(run_id: str, query: str, k: int = 8, n: int = 20) -> list[str]:
    dense = dense_search(run_id, query, n)
    try:
        sparse = bm25_search(_load_posts(run_id), query, n)
    except (ImportError, RuntimeError):
        sparse = []
    if not sparse:
        return dense[:k]
    return rrf_merge([dense, sparse])[:k]
```

Note: `faiss` and `rank_bm25` are imported inside functions deliberately — they are
the heavy/optional-dep exception in coding-standards, so a missing `rank_bm25`
degrades to dense-only instead of breaking module import.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_retrieve.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add lib/retrieve.py tests/test_retrieve.py
git commit -m "feat(rag): add dense + BM25 + hybrid search with dense fallback"
```

---

### Task 4: Self-reflective ask() loop in lib/rag.py

**Files:**
- Modify: `lib/rag.py:84-113` (the `ask` function), add constants + prompts after `ASK_SYS` (line 81)
- Test: `tests/test_rag.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rag.py`:

```python
from __future__ import annotations

import lib.rag as rag


def _patch(monkeypatch, chat_side, hits=("p1",)):
    monkeypatch.setattr(rag, "hybrid_search", lambda run_id, q, k: list(hits))
    monkeypatch.setattr(
        rag, "_load_posts_dict", lambda run_id: {"p1": {"id": "p1", "text": "ctx"}}
    )
    monkeypatch.setattr(rag, "_ensure_index", lambda run_id: True)
    calls = {"chat": []}

    def fake_chat(system, user, stage=None):
        calls["chat"].append(stage)
        return chat_side.pop(0)

    monkeypatch.setattr(rag, "chat_json", fake_chat)
    return calls


def test_ask_high_confidence_single_iteration(monkeypatch):
    side = [
        {"answer": "A", "citations": ["p1"]},   # ASK
        {"confidence": 0.9, "supported": True, "gap": ""},  # JUDGE
    ]
    calls = _patch(monkeypatch, side)
    out = rag.ask("run1", "q?")
    assert out["answer"] == "A"
    assert out["iterations"] == 1
    assert out["confidence"] == 0.9
    assert "rag_refine" not in calls["chat"]


def test_ask_low_then_high_triggers_refine_and_reretrieval(monkeypatch):
    side = [
        {"answer": "A1", "citations": []},               # ASK iter1
        {"confidence": 0.3, "supported": False, "gap": "missing X"},  # JUDGE iter1
        {"query": "q refined"},                          # REFINE
        {"answer": "A2", "citations": ["p1"]},           # ASK iter2
        {"confidence": 0.9, "supported": True, "gap": ""},  # JUDGE iter2
    ]
    calls = _patch(monkeypatch, side)
    out = rag.ask("run1", "q?")
    assert out["answer"] == "A2"
    assert out["iterations"] == 2
    assert calls["chat"].count("rag") == 2  # two answer passes


def test_ask_caps_at_max_iters(monkeypatch):
    side = [
        {"answer": "A1", "citations": []},
        {"confidence": 0.2, "supported": False, "gap": "g"},
        {"query": "q2"},
        {"answer": "A2", "citations": []},
        {"confidence": 0.25, "supported": False, "gap": "g"},
    ]
    _patch(monkeypatch, side)
    out = rag.ask("run1", "q?")
    assert out["iterations"] == 2
    assert out["answer"] == "A2"  # best (higher conf) of the two low answers


def test_ask_judge_failure_returns_answer(monkeypatch):
    side = [{"answer": "A", "citations": ["p1"]}]

    def fake_chat(system, user, stage=None):
        if not side:
            raise RuntimeError("judge boom")
        return side.pop(0)

    monkeypatch.setattr(rag, "hybrid_search", lambda run_id, q, k: ["p1"])
    monkeypatch.setattr(
        rag, "_load_posts_dict", lambda run_id: {"p1": {"id": "p1", "text": "c"}}
    )
    monkeypatch.setattr(rag, "_ensure_index", lambda run_id: True)
    monkeypatch.setattr(rag, "chat_json", fake_chat)
    out = rag.ask("run1", "q?")
    assert out["answer"] == "A"
    assert out["iterations"] == 1
    assert out["confidence"] == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_rag.py -v`
Expected: FAIL with `AttributeError: module 'lib.rag' has no attribute 'hybrid_search'`

- [ ] **Step 3: Write the implementation**

In `lib/rag.py`, replace the import block at the top (lines 1-8) with:

```python
"""FAISS-backed RAG over a run's posts: hybrid retrieval + self-reflective loop."""
from __future__ import annotations
import json
import numpy as np
import faiss
from .embed import embed_texts
from .llm import chat_json
from .retrieve import hybrid_search
from .store import run_dir
```

After `ASK_SYS = (...)` (ends line 81), add:

```python
JUDGE_SYS = (
    "You are grading a draft answer against the ONLY evidence available (the posts). "
    "Judge whether every claim in the answer is supported by the posts and whether "
    "the posts cover the question. "
    'Output JSON: {"confidence": 0.0-1.0, "supported": true/false, '
    '"gap": "what evidence is missing or unsupported, empty if none"}'
)

REFINE_SYS = (
    "Rewrite the search query to retrieve evidence that fills the stated gap. "
    "Keep it short and keyword-focused. "
    'Output JSON: {"query": "rewritten query"}'
)

REFLECT_THRESHOLD = 0.6
MAX_REFLECT_ITERS = 2


def _ensure_index(run_id: str) -> bool:
    idx_path = run_dir(run_id) / "index.faiss"
    if not idx_path.exists():
        build_index(run_id)
    return idx_path.exists()


def _load_posts_dict(run_id: str) -> dict:
    return {p["id"]: p for p in json.loads((run_dir(run_id) / "posts.json").read_text())}
```

Replace the entire `ask` function (lines 84-113) with:

```python
def ask(run_id: str, question: str, k: int = 8) -> dict:
    if not _ensure_index(run_id):
        return {"answer": "No data for this run.", "citations": [],
                "citations_detail": [], "retrieved": [], "confidence": 0.0,
                "iterations": 0}

    posts = _load_posts_dict(run_id)
    query = question
    best: dict | None = None
    best_conf = -1.0
    iters = 0

    while iters < MAX_REFLECT_ITERS:
        iters += 1
        hits = hybrid_search(run_id, query, k)
        context = "\n\n".join(
            f"[{pid}] {posts[pid]['text'][:600]}" for pid in hits if pid in posts
        )
        try:
            out = chat_json(ASK_SYS, f"Question: {question}\n\nPosts:\n{context}",
                            stage="rag")
        except Exception as e:
            return {"answer": f"LLM error: {e}", "citations": [],
                    "citations_detail": [], "retrieved": hits,
                    "confidence": 0.0, "iterations": iters}

        raw_cites = [str(c) for c in out.get("citations", [])]
        answer = {
            "answer": str(out.get("answer", "")),
            "citations": raw_cites,
            "citations_detail": [_citation_detail(run_id, c, posts) for c in raw_cites],
            "retrieved": hits,
        }

        try:
            verdict = chat_json(JUDGE_SYS,
                                f"Question: {question}\n\nAnswer: {answer['answer']}\n\n"
                                f"Posts:\n{context}", stage="rag_judge")
            conf = float(verdict.get("confidence", 1.0))
            gap = str(verdict.get("gap", ""))
        except Exception:
            answer["confidence"] = 1.0
            return {**answer, "iterations": iters}

        if conf > best_conf:
            best, best_conf = answer, conf

        if conf >= REFLECT_THRESHOLD or iters >= MAX_REFLECT_ITERS:
            break

        try:
            refined = chat_json(REFINE_SYS,
                                f"Original question: {question}\nGap: {gap}",
                                stage="rag_refine")
            query = str(refined.get("query", query)) or query
        except Exception:
            break

    return {**best, "confidence": best_conf, "iterations": iters}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_rag.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the focused suite for regressions**

Run: `.venv/bin/python -m pytest tests/test_rag.py tests/test_retrieve.py -v`
Expected: PASS (13 passed)

- [ ] **Step 6: Commit**

```bash
git add lib/rag.py tests/test_rag.py
git commit -m "feat(rag): self-reflective ask loop over hybrid retrieval"
```

---

### Task 5: Update audit + snapshot docs

**Files:**
- Modify: `.claude/submission-gap-audit.md`
- Modify: `.claude/memory/project-snapshot.md:35`

- [ ] **Step 1: Flip the audit entries to built**

In `.claude/submission-gap-audit.md`, under `### RAG architecture (Q-RAG)`, change the
three lines so they read:

```
- ✅ Hybrid search (BM25 + dense). Built in `lib/retrieve.py` (rank_bm25 + FAISS).
- ✅ Reciprocal rank fusion (RRF). `lib/retrieve.py:rrf_merge`, RRF_K=60.
- ✅ Self-reflective layer (confidence → refined re-retrieval, ≤2 iters). `lib/rag.py:ask`.
```

And update the TL;DR line: remove "hybrid+self-reflective RAG" from the fabrications
list, since it is now real.

- [ ] **Step 2: Update the snapshot RAG line**

In `.claude/memory/project-snapshot.md`, replace the RAG line (line 35):

```
- RAG: FAISS dense `IndexFlatIP` + cited Q&A (`lib/rag.py`). PURE dense, no BM25.
```

with:

```
- RAG: hybrid BM25 (`rank_bm25`) + dense FAISS `IndexFlatIP`, RRF fusion
  (`lib/retrieve.py`), self-reflective answer loop ≤2 iters (`lib/rag.py`). Cited Q&A.
```

- [ ] **Step 3: Commit**

```bash
git add .claude/submission-gap-audit.md .claude/memory/project-snapshot.md
git commit -m "docs(rag): mark hybrid + self-reflective RAG as built"
```

---

## Notes for the implementer
- Run every `pytest` from repo root `/home/shyan/Desktop/FBScraper` using `.venv/bin/python`.
- `chat_json` signature is `chat_json(system, user, stage=None)` — match it in mocks.
- Do NOT touch `build_index`, `_citation_detail`, `_normalize_cite`, `_resolve_shot_url` — reused as-is.
- `server.py` and `mcp_server.py:ask_corpus` call `ask(run_id, question)` — signature preserved, no edits there.
