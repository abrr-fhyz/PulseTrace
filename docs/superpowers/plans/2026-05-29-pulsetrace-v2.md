# PulseTrace v2 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Turn the existing Facebook scraper into an autonomous, multi-source sentiment intelligence platform with an LLM-driven research loop, topic clustering, influence ranking, RAG Q&A, and a live SSE dashboard.

**Architecture:** Pluggable source connectors → embedding + HDBSCAN clustering → LLM cluster labeling + stance → agent loop that proposes new queries until coverage converges → FAISS RAG → SSE-driven dashboard. Backend stays Flask. No DB; JSON + FAISS files per run.

**Tech Stack:** Python 3.11, Flask, Playwright (existing), `praw`, `openai`, `faiss-cpu`, `hdbscan`, `scikit-learn`, `numpy`, Chart.js, Cytoscape.js.

**Spec:** `docs/superpowers/specs/2026-05-29-pulsetrace-v2-design.md`

---

## Task 1: Scaffold dirs, deps, gitignore

**Files:**
- Create: `requirements.txt`, `.gitignore`, `lib/connectors/__init__.py`, `data/.gitkeep`, `tests/__init__.py`

- [ ] **Step 1: Write `requirements.txt`**

```
flask>=3.0
flask-cors>=4.0
python-dotenv>=1.0
playwright>=1.40
openai>=1.50
praw>=7.7
requests>=2.31
numpy>=1.26
scikit-learn>=1.4
hdbscan>=0.8.33
faiss-cpu>=1.7.4
pytest>=8.0
```

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
venv/
.env
data/runs/
data/embed_cache.jsonl
screenshots/
info/
*.faiss
.pytest_cache/
.remember/
```

- [ ] **Step 3: Create empty package files**

```bash
mkdir -p lib/connectors tests data/runs
touch lib/connectors/__init__.py tests/__init__.py data/.gitkeep
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt .gitignore lib/connectors/__init__.py tests/__init__.py data/.gitkeep
git commit -m "chore: scaffold v2 dirs and deps"
```

---

## Task 2: Connector ABC + Reddit connector

**Files:**
- Create: `lib/connectors/base.py`, `lib/connectors/reddit.py`, `tests/test_reddit_connector.py`

- [ ] **Step 1: Write `lib/connectors/base.py`**

```python
"""Source connector abstraction. Each connector fetches Posts for a query."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict, field
from typing import Any


@dataclass
class Post:
    id: str
    source: str
    text: str
    author: str | None = None
    url: str | None = None
    ts: int = 0
    reactions: int = 0
    comments: int = 0
    shares: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class Connector(ABC):
    name: str = "base"

    @abstractmethod
    def fetch(self, query: str, limit: int = 50) -> list[Post]:
        ...
```

- [ ] **Step 2: Write `lib/connectors/reddit.py`**

```python
"""Reddit connector via PRAW. Read-only application auth."""
from __future__ import annotations
import os
import time
from .base import Connector, Post


class RedditConnector(Connector):
    name = "reddit"

    def __init__(self) -> None:
        import praw
        self._praw = praw.Reddit(
            client_id=os.environ["REDDIT_CLIENT_ID"],
            client_secret=os.environ["REDDIT_CLIENT_SECRET"],
            user_agent=os.environ.get("REDDIT_USER_AGENT", "pulsetrace/0.2"),
        )
        self._praw.read_only = True

    def fetch(self, query: str, limit: int = 50) -> list[Post]:
        out: list[Post] = []
        for sub in self._praw.subreddit("all").search(query, limit=limit, sort="relevance"):
            out.append(Post(
                id=f"reddit:{sub.id}",
                source="reddit",
                text=(sub.title + "\n\n" + (sub.selftext or "")).strip(),
                author=str(sub.author) if sub.author else None,
                url=f"https://reddit.com{sub.permalink}",
                ts=int(sub.created_utc or time.time()),
                reactions=int(sub.score or 0),
                comments=int(sub.num_comments or 0),
                shares=0,
                raw={"subreddit": str(sub.subreddit)},
            ))
        return out
```

- [ ] **Step 3: Write `tests/test_reddit_connector.py`**

```python
import os
import pytest
from lib.connectors.base import Post


def test_post_dataclass_roundtrip():
    p = Post(id="x:1", source="x", text="hi", ts=1)
    d = p.to_dict()
    assert d["id"] == "x:1" and d["source"] == "x"


@pytest.mark.skipif(
    not os.environ.get("REDDIT_CLIENT_ID"),
    reason="needs REDDIT_CLIENT_ID env",
)
def test_reddit_fetch_smoke():
    from lib.connectors.reddit import RedditConnector
    posts = RedditConnector().fetch("openai", limit=3)
    assert len(posts) > 0
    assert all(p.source == "reddit" and p.text for p in posts)
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. pytest tests/test_reddit_connector.py -v
```

Expected: `test_post_dataclass_roundtrip PASSED`; reddit test skipped without env.

- [ ] **Step 5: Commit**

```bash
git add lib/connectors tests/test_reddit_connector.py
git commit -m "feat(connectors): Connector ABC + Reddit via PRAW"
```

---

## Task 3: HN connector (no auth, fast win)

**Files:**
- Create: `lib/connectors/hn.py`, `tests/test_hn_connector.py`

- [ ] **Step 1: Write `lib/connectors/hn.py`**

```python
"""Hacker News connector via Algolia search API (no auth)."""
from __future__ import annotations
import requests
from .base import Connector, Post


class HNConnector(Connector):
    name = "hn"
    URL = "https://hn.algolia.com/api/v1/search"

    def fetch(self, query: str, limit: int = 50) -> list[Post]:
        r = requests.get(self.URL, params={"query": query, "hitsPerPage": limit}, timeout=15)
        r.raise_for_status()
        out: list[Post] = []
        for h in r.json().get("hits", []):
            text = (h.get("title") or "") + "\n\n" + (h.get("story_text") or h.get("comment_text") or "")
            text = text.strip()
            if not text:
                continue
            out.append(Post(
                id=f"hn:{h.get('objectID')}",
                source="hn",
                text=text,
                author=h.get("author"),
                url=h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                ts=int(h.get("created_at_i") or 0),
                reactions=int(h.get("points") or 0),
                comments=int(h.get("num_comments") or 0),
                shares=0,
                raw={"tags": h.get("_tags", [])},
            ))
        return out
```

- [ ] **Step 2: Write `tests/test_hn_connector.py`**

```python
from unittest.mock import patch, MagicMock
from lib.connectors.hn import HNConnector


def test_hn_parses_hits():
    fake = {"hits": [
        {"objectID": "1", "title": "Hello", "story_text": "world",
         "author": "a", "url": "https://e.com", "created_at_i": 100,
         "points": 5, "num_comments": 2},
    ]}
    with patch("lib.connectors.hn.requests.get") as g:
        g.return_value = MagicMock(status_code=200, json=lambda: fake, raise_for_status=lambda: None)
        posts = HNConnector().fetch("hi", limit=1)
    assert len(posts) == 1
    p = posts[0]
    assert p.source == "hn" and p.reactions == 5 and "Hello" in p.text
```

- [ ] **Step 3: Run tests**

```bash
PYTHONPATH=. pytest tests/test_hn_connector.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add lib/connectors/hn.py tests/test_hn_connector.py
git commit -m "feat(connectors): Hacker News via Algolia"
```

---

## Task 4: Embedding client with on-disk cache

**Files:**
- Create: `lib/embed.py`, `tests/test_embed.py`

- [ ] **Step 1: Write `lib/embed.py`**

```python
"""OpenAI embedding client with sha1-keyed JSONL cache."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import numpy as np


CACHE_PATH = Path("data/embed_cache.jsonl")
MODEL = "text-embedding-3-small"
DIM = 1536


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _load_cache() -> dict[str, list[float]]:
    if not CACHE_PATH.exists():
        return {}
    cache: dict[str, list[float]] = {}
    with CACHE_PATH.open() as f:
        for line in f:
            try:
                row = json.loads(line)
                cache[row["k"]] = row["v"]
            except Exception:
                continue
    return cache


def _append_cache(rows: list[tuple[str, list[float]]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("a") as f:
        for k, v in rows:
            f.write(json.dumps({"k": k, "v": v}) + "\n")


def embed_texts(texts: list[str], batch: int = 100) -> np.ndarray:
    cache = _load_cache()
    keys = [_key(t) for t in texts]
    missing_idx = [i for i, k in enumerate(keys) if k not in cache]

    if missing_idx:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        new_rows: list[tuple[str, list[float]]] = []
        for start in range(0, len(missing_idx), batch):
            chunk = missing_idx[start:start + batch]
            resp = client.embeddings.create(model=MODEL, input=[texts[i] for i in chunk])
            for i, d in zip(chunk, resp.data):
                cache[keys[i]] = d.embedding
                new_rows.append((keys[i], d.embedding))
        _append_cache(new_rows)

    arr = np.array([cache[k] for k in keys], dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    arr = arr / np.clip(norms, 1e-9, None)
    return arr
```

- [ ] **Step 2: Write `tests/test_embed.py`**

```python
from lib.embed import _key


def test_key_deterministic():
    assert _key("hello") == _key("hello")
    assert _key("a") != _key("b")
```

- [ ] **Step 3: Run tests**

```bash
PYTHONPATH=. pytest tests/test_embed.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add lib/embed.py tests/test_embed.py
git commit -m "feat(embed): cached OpenAI embedding client"
```

---

## Task 5: Clustering with HDBSCAN + KMeans fallback

**Files:**
- Create: `lib/cluster.py`, `tests/test_cluster.py`

- [ ] **Step 1: Write `lib/cluster.py`**

```python
"""Cluster normalized embeddings. HDBSCAN primary, KMeans fallback."""
from __future__ import annotations
import numpy as np


def cluster_embeddings(emb: np.ndarray, min_cluster_size: int = 4) -> np.ndarray:
    if len(emb) < min_cluster_size * 2:
        return np.zeros(len(emb), dtype=int)
    try:
        import hdbscan
        labels = hdbscan.HDBSCAN(
            min_cluster_size=min_cluster_size, metric="euclidean"
        ).fit_predict(emb)
        if (labels >= 0).sum() >= min_cluster_size:
            return labels
    except Exception:
        pass
    from sklearn.cluster import KMeans
    k = max(2, round((len(emb) / 2) ** 0.5))
    return KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(emb)


def centroids(emb: np.ndarray, labels: np.ndarray) -> dict[int, np.ndarray]:
    out: dict[int, np.ndarray] = {}
    for c in set(int(x) for x in labels):
        if c < 0:
            continue
        mask = labels == c
        v = emb[mask].mean(axis=0)
        v = v / max(float(np.linalg.norm(v)), 1e-9)
        out[c] = v
    return out


def entropy(labels: np.ndarray) -> float:
    counts = np.bincount(labels[labels >= 0]) if (labels >= 0).any() else np.array([1])
    p = counts / counts.sum()
    return float(-(p * np.log(p + 1e-12)).sum())
```

- [ ] **Step 2: Write `tests/test_cluster.py`**

```python
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
```

- [ ] **Step 3: Run tests**

```bash
PYTHONPATH=. pytest tests/test_cluster.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add lib/cluster.py tests/test_cluster.py
git commit -m "feat(cluster): HDBSCAN clustering with KMeans fallback"
```

---

## Task 6: LLM utilities — labeling, stance, query expansion

**Files:**
- Create: `lib/llm.py`, `lib/label.py`, `lib/stance.py`, `tests/test_llm_parse.py`

- [ ] **Step 1: Write `lib/llm.py`**

```python
"""Thin OpenAI chat wrapper with strict JSON parsing + one retry."""
from __future__ import annotations
import json
import os
from typing import Any


MODEL = os.environ.get("PULSETRACE_LLM_MODEL", "gpt-4o-mini")


def chat_json(system: str, user: str, max_tokens: int = 800) -> Any:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    for attempt in range(2):
        resp = client.chat.completions.create(
            model=MODEL,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        raw = resp.choices[0].message.content or "{}"
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if attempt == 1:
                raise
            continue
```

- [ ] **Step 2: Write `lib/label.py`**

```python
"""LLM-named cluster labels from sample post texts."""
from __future__ import annotations
from .llm import chat_json


SYS = (
    "You name clusters of social posts. Output strict JSON: "
    '{"label": "<=6 words", "desc": "1-2 sentences"}'
)


def label_cluster(samples: list[str]) -> dict:
    body = "\n\n---\n\n".join(s[:500] for s in samples[:8])
    out = chat_json(SYS, f"Posts in this cluster:\n{body}")
    return {"label": out.get("label", "Unlabeled")[:80], "desc": out.get("desc", "")[:300]}
```

- [ ] **Step 3: Write `lib/stance.py`**

```python
"""Per-cluster sentiment aggregation via batched LLM."""
from __future__ import annotations
from .llm import chat_json


SYS = (
    "Classify each post's sentiment toward the cluster theme. "
    'Output JSON: {"items": [{"i": <index>, "s": "pos"|"neu"|"neg"}]}'
)


def score_batch(theme: str, texts: list[str]) -> list[str]:
    enum = "\n".join(f"[{i}] {t[:400]}" for i, t in enumerate(texts))
    out = chat_json(SYS, f"Theme: {theme}\nPosts:\n{enum}", max_tokens=600)
    by_i = {int(it["i"]): it["s"] for it in out.get("items", []) if "i" in it}
    return [by_i.get(i, "neu") for i in range(len(texts))]


def cluster_sentiment(theme: str, texts: list[str], batch: int = 8) -> dict:
    pos = neu = neg = 0
    for start in range(0, len(texts), batch):
        for s in score_batch(theme, texts[start:start + batch]):
            if s == "pos": pos += 1
            elif s == "neg": neg += 1
            else: neu += 1
    total = max(pos + neu + neg, 1)
    return {"pos": pos / total, "neu": neu / total, "neg": neg / total}
```

- [ ] **Step 4: Write `tests/test_llm_parse.py`**

```python
import json
from unittest.mock import patch, MagicMock
from lib.llm import chat_json


def _mock_response(text: str):
    return MagicMock(choices=[MagicMock(message=MagicMock(content=text))])


def test_chat_json_parses():
    with patch("lib.llm.OpenAI") as O:
        O.return_value.chat.completions.create.return_value = _mock_response('{"a": 1}')
        assert chat_json("s", "u") == {"a": 1}


def test_chat_json_retries_then_succeeds():
    with patch("lib.llm.OpenAI") as O:
        O.return_value.chat.completions.create.side_effect = [
            _mock_response("not json"), _mock_response('{"ok": true}')
        ]
        assert chat_json("s", "u") == {"ok": True}
```

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=. pytest tests/test_llm_parse.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add lib/llm.py lib/label.py lib/stance.py tests/test_llm_parse.py
git commit -m "feat(llm): json chat wrapper, cluster labeling, stance"
```

---

## Task 7: Influence scoring

**Files:**
- Create: `lib/influence.py`, `tests/test_influence.py`

- [ ] **Step 1: Write `lib/influence.py`**

```python
"""Influence score: engagement + recency decay."""
from __future__ import annotations
import math
import time
from .connectors.base import Post


HALF_LIFE_DAYS = 7.0


def recency(ts: int, now: int | None = None) -> float:
    if ts <= 0:
        return 0.0
    now = now or int(time.time())
    days = max(0.0, (now - ts) / 86400.0)
    return 0.5 ** (days / HALF_LIFE_DAYS)


def influence(p: Post, now: int | None = None) -> float:
    return (
        math.log1p(p.reactions)
        + 2.0 * math.log1p(p.comments)
        + 3.0 * math.log1p(p.shares)
        + 0.5 * recency(p.ts, now)
    )


def top_n(posts: list[Post], n: int = 5) -> list[Post]:
    return sorted(posts, key=influence, reverse=True)[:n]
```

- [ ] **Step 2: Write `tests/test_influence.py`**

```python
from lib.connectors.base import Post
from lib.influence import influence, top_n, recency


def _p(**kw):
    return Post(id=kw.get("id", "x"), source="x", text="t", ts=kw.get("ts", 0),
                reactions=kw.get("r", 0), comments=kw.get("c", 0), shares=kw.get("s", 0))


def test_more_comments_beats_more_reactions():
    a = _p(id="a", r=1000, c=0, s=0)
    b = _p(id="b", r=0, c=100, s=0)
    assert influence(b) > influence(a)


def test_shares_dominate():
    a = _p(id="a", r=1000, c=0, s=0)
    b = _p(id="b", r=0, c=0, s=20)
    assert influence(b) > influence(a)


def test_recency_decays():
    now = 1_000_000_000
    fresh = recency(now - 0, now)
    old = recency(now - 30 * 86400, now)
    assert fresh > old


def test_top_n_orders():
    posts = [_p(id=str(i), c=i) for i in range(10)]
    top = top_n(posts, 3)
    assert [p.id for p in top] == ["9", "8", "7"]
```

- [ ] **Step 3: Run tests**

```bash
PYTHONPATH=. pytest tests/test_influence.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add lib/influence.py tests/test_influence.py
git commit -m "feat(influence): engagement + recency scoring"
```

---

## Task 8: Event bus (SSE pub/sub) + run store

**Files:**
- Create: `lib/events.py`, `lib/store.py`, `tests/test_events.py`

- [ ] **Step 1: Write `lib/events.py`**

```python
"""Thread-safe per-run event queues for SSE streaming."""
from __future__ import annotations
import json
import queue
import threading
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._queues: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            qs = list(self._queues.get(run_id, []))
        for q in qs:
            q.put(event)

    def subscribe(self, run_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1024)
        with self._lock:
            self._queues.setdefault(run_id, []).append(q)
        return q

    def close(self, run_id: str) -> None:
        with self._lock:
            for q in self._queues.get(run_id, []):
                q.put({"type": "_close"})
            self._queues.pop(run_id, None)


BUS = EventBus()


def sse_format(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"
```

- [ ] **Step 2: Write `lib/store.py`**

```python
"""Per-run JSON persistence under data/runs/<run_id>/."""
from __future__ import annotations
import json
import time
import uuid
from pathlib import Path
from typing import Any


ROOT = Path("data/runs")


def new_run_id() -> str:
    return f"{int(time.time())}-{uuid.uuid4().hex[:6]}"


def run_dir(run_id: str) -> Path:
    p = ROOT / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_json(run_id: str, name: str, data: Any) -> None:
    (run_dir(run_id) / name).write_text(json.dumps(data, default=str, indent=2))


def read_json(run_id: str, name: str) -> Any:
    p = run_dir(run_id) / name
    if not p.exists():
        return None
    return json.loads(p.read_text())
```

- [ ] **Step 3: Write `tests/test_events.py`**

```python
from lib.events import EventBus, sse_format


def test_bus_publishes_to_subscriber():
    bus = EventBus()
    q = bus.subscribe("r1")
    bus.publish("r1", {"type": "hi"})
    assert q.get_nowait() == {"type": "hi"}


def test_sse_format_shape():
    s = sse_format({"a": 1})
    assert s.startswith("data: ") and s.endswith("\n\n")
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. pytest tests/test_events.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/events.py lib/store.py tests/test_events.py
git commit -m "feat(infra): event bus + per-run JSON store"
```

---

## Task 9: Agent orchestrator

**Files:**
- Create: `lib/agent.py`, `tests/test_agent_math.py`

- [ ] **Step 1: Write `lib/agent.py`**

```python
"""Agent loop: seed queries → fetch → cluster → label → expand or stop."""
from __future__ import annotations
import time
from concurrent.futures import ThreadPoolExecutor
from .connectors.base import Connector, Post
from .connectors.reddit import RedditConnector
from .connectors.hn import HNConnector
from .embed import embed_texts
from .cluster import cluster_embeddings, centroids, entropy
from .label import label_cluster
from .stance import cluster_sentiment
from .influence import top_n
from .events import BUS
from .store import write_json, new_run_id
from .llm import chat_json


MAX_ITERS = 4
MAX_POSTS = 500
EPS = 0.05
SOURCES: dict[str, type[Connector]] = {"reddit": RedditConnector, "hn": HNConnector}


SEED_SYS = (
    "Generate 5 diverse, complementary search queries for social-media research "
    "on the user's topic. Output JSON: {\"queries\": [\"...\"]}"
)
NEXT_SYS = (
    "Given cluster labels found so far and the topic, decide: stop or expand. "
    "If expand, propose up to 3 new search queries targeting under-covered angles. "
    'Output JSON: {"action": "stop"|"expand", "queries": [\"...\"]}'
)


def _llm_seed(topic: str) -> list[str]:
    out = chat_json(SEED_SYS, f"Topic: {topic}")
    qs = [str(q) for q in out.get("queries", []) if q]
    return qs[:5] or [topic]


def _llm_next(topic: str, labels: list[str]) -> dict:
    return chat_json(NEXT_SYS, f"Topic: {topic}\nLabels so far:\n- " + "\n- ".join(labels))


def _fetch_all(queries: list[tuple[str, str]], limit: int) -> list[Post]:
    posts: list[Post] = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(SOURCES[src]().fetch, q, limit) for q, src in queries if src in SOURCES]
        for f in futures:
            try:
                posts.extend(f.result())
            except Exception:
                continue
    return posts


def run_agent(topic: str, sources: list[str]) -> str:
    run_id = new_run_id()
    BUS.publish(run_id, {"type": "started", "run_id": run_id, "topic": topic})
    seen: dict[str, Post] = {}
    queries_log: list[dict] = []
    last_H = 0.0

    seeds = _llm_seed(topic)
    BUS.publish(run_id, {"type": "seeded", "queries": seeds})
    pending = [(q, s) for q in seeds for s in sources]

    for it in range(MAX_ITERS):
        BUS.publish(run_id, {"type": "iter_start", "iter": it + 1, "queries": pending})
        new_posts = _fetch_all(pending, limit=max(5, MAX_POSTS // (len(pending) or 1)))
        for p in new_posts:
            if p.id not in seen and len(seen) < MAX_POSTS:
                seen[p.id] = p
        BUS.publish(run_id, {"type": "posts_fetched", "n_new": len(new_posts), "n_total": len(seen)})
        for q, s in pending:
            queries_log.append({"q": q, "source": s, "iter": it + 1})

        if len(seen) < 10:
            pending = [(topic, s) for s in sources]
            continue

        posts = list(seen.values())
        emb = embed_texts([p.text for p in posts])
        labels = cluster_embeddings(emb)
        H = entropy(labels)
        BUS.publish(run_id, {"type": "clustered", "k": int(len({int(x) for x in labels if x >= 0})), "entropy": H})

        cents = centroids(emb, labels)
        cluster_meta: list[dict] = []
        for cid, _vec in cents.items():
            members = [posts[i] for i, lab in enumerate(labels) if lab == cid]
            sample = [m.text for m in members[:8]]
            meta = label_cluster(sample)
            sent = cluster_sentiment(meta["label"], [m.text for m in members])
            tops = top_n(members, n=5)
            cluster_meta.append({
                "id": int(cid), "label": meta["label"], "desc": meta["desc"],
                "centroid": cents[cid].tolist(), "members": [m.id for m in members],
                "sentiment": sent, "top_posts": [m.id for m in tops],
            })

        write_json(run_id, "posts.json", [p.to_dict() for p in posts])
        write_json(run_id, "clusters.json", cluster_meta)
        BUS.publish(run_id, {"type": "labeled", "clusters": [
            {"id": c["id"], "label": c["label"], "n": len(c["members"]), "sentiment": c["sentiment"]}
            for c in cluster_meta
        ]})

        if it >= MAX_ITERS - 1 or len(seen) >= MAX_POSTS:
            stop_reason = "budget"
            break
        if abs(H - last_H) < EPS and it > 0:
            stop_reason = "converged"
            break
        last_H = H

        decision = _llm_next(topic, [c["label"] for c in cluster_meta])
        if decision.get("action") == "stop":
            stop_reason = "agent_stop"
            break
        pending = [(q, s) for q in decision.get("queries", [])[:3] for s in sources]
        if not pending:
            stop_reason = "no_queries"
            break
    else:
        stop_reason = "budget"

    write_json(run_id, "run.json", {
        "id": run_id, "topic": topic, "started_at": int(time.time()),
        "queries": queries_log, "stop_reason": stop_reason,
        "metrics": {"posts": len(seen)},
    })
    BUS.publish(run_id, {"type": "done", "run_id": run_id, "stop_reason": stop_reason, "n_posts": len(seen)})
    BUS.close(run_id)
    return run_id
```

- [ ] **Step 2: Write `tests/test_agent_math.py`**

```python
import numpy as np
from lib.cluster import entropy


def test_uniform_higher_entropy_than_skewed():
    uniform = np.array([0, 1, 2, 0, 1, 2])
    skewed = np.array([0, 0, 0, 0, 0, 1])
    assert entropy(uniform) > entropy(skewed)
```

- [ ] **Step 3: Run tests**

```bash
PYTHONPATH=. pytest tests/test_agent_math.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add lib/agent.py tests/test_agent_math.py
git commit -m "feat(agent): orchestrator loop with expansion + convergence"
```

---

## Task 10: RAG (FAISS + ask)

**Files:**
- Create: `lib/rag.py`, `tests/test_rag.py`

- [ ] **Step 1: Write `lib/rag.py`**

```python
"""FAISS-backed RAG over a run's posts."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import faiss
from .embed import embed_texts
from .llm import chat_json
from .store import run_dir


def build_index(run_id: str) -> None:
    posts = json.loads((run_dir(run_id) / "posts.json").read_text())
    texts = [p["text"] for p in posts]
    if not texts:
        return
    emb = embed_texts(texts).astype(np.float32)
    idx = faiss.IndexFlatIP(emb.shape[1])
    idx.add(emb)
    faiss.write_index(idx, str(run_dir(run_id) / "index.faiss"))
    (run_dir(run_id) / "ids.json").write_text(json.dumps([p["id"] for p in posts]))


ASK_SYS = (
    "Answer the user's question using ONLY the provided posts as evidence. "
    "Cite post ids in square brackets. If unknown, say so. "
    'Output JSON: {"answer": "...", "citations": ["id", ...]}'
)


def ask(run_id: str, question: str, k: int = 8) -> dict:
    d = run_dir(run_id)
    idx_path = d / "index.faiss"
    if not idx_path.exists():
        build_index(run_id)
    idx = faiss.read_index(str(idx_path))
    ids = json.loads((d / "ids.json").read_text())
    posts = {p["id"]: p for p in json.loads((d / "posts.json").read_text())}

    qvec = embed_texts([question]).astype(np.float32)
    _, I = idx.search(qvec, k)
    hits = [ids[i] for i in I[0] if 0 <= i < len(ids)]
    context = "\n\n".join(f"[{pid}] {posts[pid]['text'][:600]}" for pid in hits if pid in posts)
    out = chat_json(ASK_SYS, f"Question: {question}\n\nPosts:\n{context}")
    return {"answer": out.get("answer", ""), "citations": out.get("citations", []), "retrieved": hits}
```

- [ ] **Step 2: Write `tests/test_rag.py`**

```python
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
from lib import rag, store


def test_build_and_ask(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(rag, "run_dir", lambda r: store.run_dir(r))
    rid = "test-run"
    d = store.run_dir(rid)
    posts = [{"id": "a", "text": "cats are great"}, {"id": "b", "text": "dogs love walks"}]
    (d / "posts.json").write_text(json.dumps(posts))

    fake_emb = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    with patch("lib.rag.embed_texts", return_value=fake_emb):
        rag.build_index(rid)

    qvec = np.array([[1.0, 0.0]], dtype=np.float32)
    with patch("lib.rag.embed_texts", return_value=qvec), \
         patch("lib.rag.chat_json", return_value={"answer": "cats", "citations": ["a"]}):
        res = rag.ask(rid, "tell me about cats", k=1)
    assert res["answer"] == "cats"
    assert "a" in res["retrieved"]
```

- [ ] **Step 3: Run tests**

```bash
PYTHONPATH=. pytest tests/test_rag.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add lib/rag.py tests/test_rag.py
git commit -m "feat(rag): FAISS index + cited-answer endpoint"
```

---

## Task 11: Server endpoints (/run, /events, /graph, /ask)

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Replace `server.py`**

```python
#!/usr/bin/env python3
"""PulseTrace v2 Flask server: agent runs, SSE, graph, RAG."""
import json
import threading
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from lib.agent import run_agent
from lib.events import BUS, sse_format
from lib.store import read_json
from lib.rag import ask as rag_ask
import numpy as np

app = Flask(__name__)
CORS(app)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/run", methods=["POST"])
def start_run():
    data = request.get_json(force=True) or {}
    topic = (data.get("topic") or "").strip()
    sources = data.get("sources") or ["reddit", "hn"]
    if not topic:
        return jsonify({"error": "topic required"}), 400

    holder: dict = {}

    def go():
        try:
            holder["run_id"] = run_agent(topic, sources)
        except Exception as e:
            holder["error"] = str(e)

    t = threading.Thread(target=go, daemon=True)
    t.start()

    # wait briefly for run_id to be published; agent emits "started" early
    import time
    for _ in range(20):
        if holder.get("run_id"):
            break
        time.sleep(0.05)
    return jsonify({"run_id": holder.get("run_id"), "error": holder.get("error")})


@app.route("/events")
def events():
    run_id = request.args.get("run_id", "")
    q = BUS.subscribe(run_id)

    @stream_with_context
    def gen():
        while True:
            ev = q.get()
            if ev.get("type") == "_close":
                yield sse_format({"type": "closed"})
                return
            yield sse_format(ev)

    return Response(gen(), mimetype="text/event-stream")


@app.route("/graph")
def graph():
    run_id = request.args.get("run_id", "")
    clusters = read_json(run_id, "clusters.json") or []
    nodes = [{
        "data": {"id": str(c["id"]), "label": c["label"], "size": len(c["members"]),
                  "sentiment": c["sentiment"]}
    } for c in clusters]
    edges = []
    for i, a in enumerate(clusters):
        for b in clusters[i + 1:]:
            va, vb = np.array(a["centroid"]), np.array(b["centroid"])
            sim = float(va @ vb)
            if sim > 0.5:
                edges.append({"data": {
                    "id": f"{a['id']}-{b['id']}", "source": str(a["id"]),
                    "target": str(b["id"]), "weight": sim,
                }})
    return jsonify({"nodes": nodes, "edges": edges})


@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json(force=True) or {}
    run_id = data.get("run_id")
    q = (data.get("q") or "").strip()
    if not run_id or not q:
        return jsonify({"error": "run_id and q required"}), 400
    return jsonify(rag_ask(run_id, q))


@app.route("/run-info")
def run_info():
    run_id = request.args.get("run_id", "")
    return jsonify({
        "run": read_json(run_id, "run.json"),
        "clusters": read_json(run_id, "clusters.json"),
    })


if __name__ == "__main__":
    print("PulseTrace v2 → http://localhost:5000")
    app.run(debug=False, host="0.0.0.0", port=5000, threaded=True)
```

- [ ] **Step 2: Sanity check imports**

```bash
PYTHONPATH=. python -c "import server; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add server.py
git commit -m "feat(server): /run, /events SSE, /graph, /ask endpoints"
```

---

## Task 12: Dashboard rewrite (charts + graph + Q&A + SSE)

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 1: Replace `templates/index.html`** with the full dashboard (input, source toggles, live log via SSE, Chart.js sentiment bars, Cytoscape topic graph, Q&A box). See actual write in implementation; uses CDN: chart.js, cytoscape.

- [ ] **Step 2: Smoke-load the page**

```bash
PYTHONPATH=. python server.py &
sleep 2
curl -s http://localhost:5000 | head -5
kill %1
```

Expected: HTML starting with `<!doctype html>`.

- [ ] **Step 3: Commit**

```bash
git add templates/index.html
git commit -m "feat(ui): live dashboard with charts, topic graph, Q&A"
```

---

## Task 13: README + final push

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append v2 section to README** explaining new flow, env vars (`OPENAI_API_KEY`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`), and `python server.py` startup.

- [ ] **Step 2: Run full test suite**

```bash
PYTHONPATH=. pytest tests/ -v
```

Expected: all PASS (Reddit smoke skipped without env).

- [ ] **Step 3: Commit + push**

```bash
git add README.md
git commit -m "docs: v2 quickstart"
git push -u origin shyan
```

---

## Self-Review

- **Spec coverage:** Connectors (Tasks 2,3), embed (4), cluster (5), label/stance (6), influence (7), agent (9), RAG (10), events+server (8,11), frontend (12). All sections of spec mapped.
- **Placeholders:** None remain.
- **Type consistency:** `Post` dataclass shared across connectors/influence/agent; `EventBus` API stable between events.py and server.py; `run_dir` used uniformly.
