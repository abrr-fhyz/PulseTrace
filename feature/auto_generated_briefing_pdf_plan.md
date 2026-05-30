# Auto-Generated Briefing PDF — Implementation Plan

> Senior-SWE rewrite. Grounded in current code. Every reference is a real file:line.
> Implementer should touch ONLY files listed in §10 "Touchpoint map" and reuse
> the helpers in §3 "Existing code to reuse". Do not re-search the repo.

---

## 1. Goal (unchanged)

End-of-run, produce a one-page executive PDF inside the run dir:
- topic + run metadata
- top 3–4 clusters with sentiment bars
- top 3 quoted posts per cluster with exact citations
- 2–3 FB screenshot thumbnails when available
- generated automatically on run completion, on-demand via HTTP, and via CLI

---

## 2. Ground truth — what's already on disk

Per-run artifacts live under `data/runs/<run_id>/` (see `lib/store.py:11` `ROOT`).
Helpers: `lib/store.py:14 new_run_id`, `lib/store.py:18 run_dir`, `lib/store.py:24 write_json`, `lib/store.py:30 read_json`.

### 2.1 `run.json` — written at `lib/agent.py:217`

```json
{
  "id": "<run_id>",
  "topic": "<str>",
  "sources": ["facebook", ...],
  "started_at": <unix_ts>,
  "queries": [{"q": "...", "source": "facebook", "iter": 1}, ...],
  "stop_reason": "budget" | "iters" | "converged" | "agent_stop" | "no_queries" | "embed_error",
  "metrics": {"posts": <int>, "clusters": <int>}
}
```

⚠️ There is no `finished_at` field today — if briefing wants run duration, add it at `lib/agent.py:217` in the same write.

### 2.2 `clusters.json` — written at `lib/agent.py:187`, built `lib/agent.py:176-184`

```json
[
  {
    "id": 0,
    "label": "<str>",
    "desc": "<str>",
    "centroid": [<float>...],   // do NOT render — internal
    "members": ["<post_id>", ...],
    "sentiment": {"pos": 0.x, "neu": 0.x, "neg": 0.x},
    "top_posts": ["<post_id>", ...]   // pre-ranked by lib/influence.py:top_n
  }
]
```

`top_posts` is already the influence-ranked top-5 per cluster — reuse it as-is.
Do NOT recompute influence.

### 2.3 `posts.json` — list of `Post.to_dict()` (`lib/connectors/base.py:8`)

```json
{
  "id": "facebook:abc123",     // "<source>:<native_id>"
  "source": "facebook" | "reddit" | "hn" | "x" | "instagram",
  "text": "<str>",
  "author": "<str|null>",
  "url": "<str|null>",
  "ts": <unix_ts>,
  "reactions": <int>, "comments": <int>, "shares": <int>,
  "raw": { "shot": "<filename.png>"?, "query": "<q>"?, ... }
}
```

### 2.4 Screenshot layout

`data/runs/<run_id>/shots/iter_<N>/<filename>.png`
(written by `FacebookConnector` when constructed with `shots_dir=` — see `lib/agent.py:60-75` `_build_connector`).

`post.raw["shot"]` holds the bare filename. Resolve to a URL via
**`lib/rag.py:24 _resolve_shot_url(run_id, shot_name)`** — already returns
`/shots/<run_id>/<iter_name>/<filename>`. Reuse, do not reinvent.

The original plan said `screenshots/{post_id}.png` — **wrong**. Delete that assumption.

### 2.5 What does NOT exist

- No `summary.txt`, no exec-summary blob, no global stance trace. `lib/summary.py` is the v1 Facebook-only summarizer and is unrelated; do not import it.
- No screenshots for non-Facebook sources. Reddit/HN/X/IG posts have no `raw["shot"]`.

---

## 3. Existing code to reuse — DO NOT reimplement

| Need | Use this | Location |
|---|---|---|
| Run dir path | `run_dir(run_id)` | `lib/store.py:18` |
| Load/save JSON | `read_json`, `write_json` | `lib/store.py:24,30` |
| Influence ranking | already baked into `cluster["top_posts"]` | (don't recompute) |
| Resolve screenshot URL | `_resolve_shot_url(run_id, name)` | `lib/rag.py:24` |
| Citation dict shape | `_citation_detail(run_id, raw, posts)` | `lib/rag.py:38` |
| LLM JSON call (for optional exec summary) | `chat_json(system, user, max_tokens, stage="briefing")` | `lib/llm.py:125` |
| SSE event emission | `BUS.publish(run_id, {...})` | `lib/events.py` |
| Post dataclass | `Post` | `lib/connectors/base.py:8` |

---

## 4. Module to add: `lib/briefing.py`

**Functional, not OO.** The "RunBriefingGenerator" class in the original plan
is overkill — this is a pure transform from on-disk JSON to HTML/PDF.

```python
# lib/briefing.py
from __future__ import annotations
from pathlib import Path
from .store import run_dir, read_json, write_json
from .rag import _resolve_shot_url
from .llm import chat_json

MAX_CLUSTERS = 4
QUOTES_PER_CLUSTER = 3
QUOTE_MAX_CHARS = 220
MAX_THUMBNAILS = 3

def build(run_id: str, *, with_pdf: bool = True,
          exec_summary: bool = True) -> dict:
    """Returns {"html": Path, "pdf": Path|None, "manifest": Path}.
    Idempotent — overwrites prior briefing/ on each call."""

def _load(run_id) -> tuple[dict, list[dict], dict[str, dict]]: ...
def _select_clusters(clusters, posts_by_id) -> list[dict]: ...
def _quotes(cluster, posts_by_id) -> list[dict]: ...
def _thumbnails(run_id, clusters, posts_by_id) -> list[dict]: ...
def _exec_summary(topic, clusters) -> str: ...   # one chat_json call
def _render_html(ctx) -> str: ...                # inline f-string template
def _render_pdf(html_path, pdf_path) -> bool: ...  # weasyprint, optional
```

### 4.1 Cluster selection rule

Rank by `len(members)` desc, then by `sum(post.reactions+comments+shares)` of
`top_posts` desc, take top `MAX_CLUSTERS`. Skip clusters where `id == -1`
(HDBSCAN noise — already filtered by `lib/agent.py:158` but defend anyway).

### 4.2 Quote selection rule

For each selected cluster, take first `QUOTES_PER_CLUSTER` IDs from
`cluster["top_posts"]` (already ranked). For each:
- post text trimmed to `QUOTE_MAX_CHARS`, append `…` if cut
- citation line: `<source> · <author or "anon"> · ❤ {reactions} 💬 {comments} ↻ {shares}`
- if `post["url"]` set → wrap text in `<a href=...>`
- if `post["raw"]["shot"]` set → resolve via `_resolve_shot_url`, attach as `shot_url`

### 4.3 Thumbnail selection rule

Walk selected clusters in order, collect first post per cluster with a
resolvable shot URL, stop at `MAX_THUMBNAILS`. No placeholder boxes — if zero
shots, just omit the section. (Plan's "No screenshot available" box wastes
the one-page budget.)

### 4.4 Optional exec summary

One `chat_json` call, gated by `exec_summary=True`. System prompt:

```
You are a senior intelligence analyst. Given a topic and cluster labels with
sentiment ratios, write ONE paragraph (60-90 words) summarising the
conversation landscape. No bullet points, no markdown. Output JSON:
{"summary": "..."}
```

Cost: ~300 tokens in, ~150 out → <$0.0005 on gemini-2.5-flash-lite.
If the call fails (`except Exception`), set summary to `""` and continue —
**do not break the briefing for an LLM hiccup** (same pattern as
`lib/agent.py:167-174`).

---

## 5. Output layout

Write under `data/runs/<run_id>/briefing/`:

- `briefing.html` — canonical artifact. Embeds screenshots as **relative**
  paths (`../shots/iter_N/foo.png`) so the file is portable when viewed
  locally AND so weasyprint can resolve image refs from a `base_url=run_dir`.
- `briefing.pdf` — only if weasyprint import succeeds.
- `briefing.json` — manifest:
  ```json
  {"generated_at": ts, "run_id": "...", "topic": "...",
   "clusters_used": [<ids>], "quotes": <int>, "thumbnails": <int>,
   "pdf": true|false, "exec_summary": true|false}
  ```

**Drop the `briefing.md` artifact** from the original plan. It's a third
representation nobody reads. HTML is the single source.

---

## 6. HTML template

Keep it as a Python f-string inside `lib/briefing.py` — do **not** add a
Jinja file under `templates/`. `templates/` is for the SPA dashboard; mixing
briefing markup there couples concerns.

Print CSS requirements:
- `@page { size: A4; margin: 14mm; }`
- single column, no SPA chrome
- sentiment bar = 3-segment flex div, widths from `cluster.sentiment`
- cluster cards in CSS grid `repeat(2, 1fr)` (2x2 for 4 clusters)
- thumbnails row at bottom, `max-height: 80px`
- font stack: `system-ui, -apple-system, sans-serif` (no web fonts — weasyprint hates them)

---

## 7. PDF rendering

```python
def _render_pdf(html_path: Path, pdf_path: Path) -> bool:
    try:
        from weasyprint import HTML
    except ImportError:
        return False
    HTML(filename=str(html_path), base_url=str(html_path.parent.parent)).write_pdf(str(pdf_path))
    return True
```

`base_url=run_dir` so the `../shots/...` relative paths resolve. Wrap in
`try/except Exception` — weasyprint sometimes blows up on missing system
libs (`libpango`, `libcairo`). If it fails, log and return `False`; HTML
stays valid.

---

## 8. Integration points

### 8.1 End-of-run hook — `lib/agent.py:217-229`

After `write_json(run_id, "run.json", ...)` and before `BUS.publish({"type": "done"...})`:

```python
try:
    from .briefing import build as build_briefing
    b = build_briefing(run_id, with_pdf=True, exec_summary=True)
    BUS.publish(run_id, {"type": "briefing_ready",
                          "html": f"/run/{run_id}/briefing/html",
                          "pdf": f"/run/{run_id}/briefing/pdf" if b["pdf"] else None})
except Exception as e:
    BUS.publish(run_id, {"type": "briefing_error", "err": str(e)})
```

Wrap in try/except — briefing failure must not break the `done` event.

### 8.2 HTTP routes — add to `server.py` near the `/shots/...` block (`server.py:165-193`)

```python
@app.route("/run/<run_id>/briefing/html")
def briefing_html(run_id):
    p = run_dir(run_id) / "briefing" / "briefing.html"
    if not p.exists():
        try: build_briefing(run_id)
        except Exception as e: return jsonify({"error": str(e)}), 500
    return Response(p.read_text(), mimetype="text/html")

@app.route("/run/<run_id>/briefing/pdf")
def briefing_pdf(run_id):
    p = run_dir(run_id) / "briefing" / "briefing.pdf"
    if not p.exists():
        try: build_briefing(run_id, with_pdf=True)
        except Exception as e: return jsonify({"error": str(e)}), 500
    if not p.exists():
        return jsonify({"error": "PDF unavailable (weasyprint not installed)"}), 501
    return Response(p.read_bytes(), mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="briefing-{run_id}.pdf"'})

@app.route("/run/<run_id>/briefing/manifest")
def briefing_manifest(run_id):
    m = run_dir(run_id) / "briefing" / "briefing.json"
    return (Response(m.read_text(), mimetype="application/json")
            if m.exists() else (jsonify({"error": "not generated"}), 404))
```

Imports needed at top of `server.py`: `from lib.briefing import build as build_briefing` (already has `from lib.store import run_dir` block — check).

### 8.3 CLI — `main.py:30` (`choices=[...]`)

Extend `argparse` choices to include `briefing`. Add a branch in the
dispatcher (`main.py:55+`):

```python
elif args.command == 'briefing':
    import argparse as _ap
    sp = _ap.ArgumentParser()
    sp.add_argument('--run-id', required=True)
    sp.add_argument('--no-pdf', action='store_true')
    sp.add_argument('--no-summary', action='store_true')
    a = sp.parse_args(remaining_args)
    from lib.briefing import build
    out = build(a.run_id, with_pdf=not a.no_pdf, exec_summary=not a.no_summary)
    print(out)
    return 0
```

Update the `Commands:` epilog in `main.py:14-28` so `--help` reflects the new command.

### 8.4 Dashboard UI — `templates/index.html`

Subscribe to the existing SSE stream (`server.py:243 /events`). When a
`briefing_ready` event arrives, surface a "📄 Download briefing PDF" pill
button in the run header. **Do not add a new SPA route** (`#/briefing`) —
the PDF opens in a new tab via the existing `/run/<id>/briefing/pdf` route.

Minimal edit: in the SSE message handler, add a branch for
`msg.type === 'briefing_ready'` that toggles visibility on a hidden anchor.
Keep all changes inside the existing `<script>` block — do not add new
top-level views.

---

## 9. Dependencies

Add to `requirements.txt`:

```
weasyprint>=62.0
```

Mark as optional in install docs: weasyprint pulls in `libpango`, `libcairo`,
`libgdk-pixbuf`. On a fresh Debian-flavour box: `apt install libpango-1.0-0
libpangoft2-1.0-0`. If unavailable, briefing still produces HTML — degrade
gracefully (§7).

No other deps. Do **not** add Jinja2 explicitly — Flask already pulls it
and we're not using it for briefing.

---

## 10. Touchpoint map (exhaustive — implementer touches ONLY these)

| File | Action | Lines |
|---|---|---|
| `lib/briefing.py` | **create** | new file ~180 LoC |
| `lib/agent.py` | edit — add briefing hook | after line 225 (post-`write_json`) |
| `server.py` | edit — add 3 routes | after `server.py:193` |
| `main.py` | edit — extend argparse + dispatcher | lines 30 and 55+ |
| `templates/index.html` | edit — SSE handler branch + hidden anchor | inside existing `<script>`; do not add new view |
| `requirements.txt` | edit — append `weasyprint>=62.0` | last line |
| `tests/test_briefing.py` | **create** | new file |
| `.gitignore` | edit — add `data/runs/*/briefing/` if you don't want artifacts checked in | optional |

Files implementer **must not touch**: anything under `lib/connectors/`,
`lib/embed.py`, `lib/cluster.py`, `lib/llm.py` (just call `chat_json`),
`lib/rag.py` (just call `_resolve_shot_url`), `lib/backend.py`, `lib/dispatch.py`.

---

## 11. Testing

`tests/test_briefing.py`:

1. **Unit — pure functions on synthetic JSON**
   - Build a temp `data/runs/test-run-x/` with hand-crafted `run.json`,
     `clusters.json`, `posts.json` (3 clusters, 10 posts, 2 with `raw.shot`).
   - Assert `_select_clusters` orders by size+engagement.
   - Assert `_quotes` truncates at `QUOTE_MAX_CHARS` and appends `…`.
   - Assert `_thumbnails` skips posts without shots and caps at `MAX_THUMBNAILS`.
   - Assert HTML output contains topic, all selected cluster labels, and
     `<img src="../shots/...">` for resolvable shots.

2. **Integration — real artifacts**
   - Use a fixture `run_id` pointing at a small committed sample under
     `tests/fixtures/runs/sample/`. Run `build(...)`. Assert
     `briefing.html` exists, `briefing.json` parses, manifest counts match.

3. **PDF — gated**
   - `pytest.importorskip("weasyprint")`. Build, assert
     `briefing.pdf` non-empty and starts with `%PDF-`.

4. **Mock LLM**
   - Patch `lib.briefing.chat_json` to return `{"summary": "stub"}` for unit
     tests so we don't pay tokens.
   - Add a failure-path test: `chat_json` raises → briefing still succeeds
     with empty `exec_summary`.

5. **HTTP**
   - Flask test client: `GET /run/<id>/briefing/html` returns 200; missing
     `run_id` returns 500 with JSON error; `GET .../pdf` returns 501 when
     weasyprint absent.

---

## 12. Risks & mitigations (revised)

| Risk | Mitigation |
|---|---|
| weasyprint system-lib install pain | HTML is canonical. PDF route returns 501 with clear message if missing. |
| One-page overflow on long labels | Cluster label truncated to 60 chars; quote to 220 chars; cap 4 clusters × 3 quotes. |
| Run JSON schema drifts | Loader uses `.get()` with defaults for every field. Document expected keys at top of `lib/briefing.py`. |
| Briefing call slows down "done" event | Wrap in try/except in `agent.py`; emit `briefing_ready` async — `done` event always fires. |
| LLM call for exec summary fails or hangs | Single attempt, exception → empty string, briefing still completes. Stage tag `"briefing"` for log filtering. |
| FB-only screenshots → other-source runs render thumbnail-less | Acceptable. Section auto-hides when zero thumbnails. |
| `data/runs/...` paths assumed relative — but `weasyprint` needs absolute | `_render_pdf` passes `base_url=run_dir.absolute()`. |

---

## 13. What was wrong in the original plan (for reference)

1. Screenshot path `screenshots/*.png` / `screenshots/{post_id}.png` — **wrong**. Actual: `shots/iter_N/<filename>.png`, filename held in `post.raw["shot"]`.
2. "Existing text summary if available" — there is no v2 exec summary. Either generate one or omit.
3. `RunBriefingGenerator` class — overkill. Stateless functions are clearer.
4. Markdown + HTML + PDF triple-render — wasteful. HTML+PDF only.
5. Did not name `lib/store.py`, `lib/rag.py`, `lib/influence.py`, `lib/events.py` helpers to reuse — would cause reimplementation.
6. Did not specify SSE event for UI hook-in — UI would have to poll.
7. CLI integration via `main.py` ignored existing `argparse` `choices=` constraint (line 30) — extending requires editing both choices and dispatcher.
8. Did not name end-of-run hook line in `agent.py` — implementer would search.
9. weasyprint listed as "optional install marker" without specifying the system libs that actually break installs.
10. Tests section vague — no fixtures, no mocking strategy for LLM call.

---

## 14. Estimated effort

- `lib/briefing.py` + template: ~3h
- Hook + routes + CLI: ~30min
- UI SSE branch: ~20min
- Tests + fixture: ~1.5h
- weasyprint debug on local box: 30min–2h (system libs)

Total: ~half a day for a senior dev who follows §10 strictly.
