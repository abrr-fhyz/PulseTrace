# Live-Building Dashboard (Real-Time Results) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the blocking full-screen loader so the dashboard builds in real time as results arrive — KPIs climb, charts draw, opinions/talking points stream in with a typed-text effect, the graph renders — with skeleton placeholders covering the gap before first data.

**Architecture:** Presentation-only. The dashboard already renders progressively in `agent.js handle()` (KPIs, `renderClusters`, `renderSentChart`, `drawGraph`) and the sidebar Pipeline card already tracks live stages. The only thing hiding it is the `PL2` overlay. Delete the `PL2` overlay, then add: skeletons, a typed-label effect on new clusters, and a reveal animation on the voices/evidence panels. No backend or SSE-schema change.

**Tech Stack:** Vanilla JS (no build step), Flask Jinja partial, plain CSS. Helpers `$`, `elem`, `clearNode` (core.js); cluster rendering in `clusters.js`.

---

## Background facts (verified, do not re-derive)

- `static/js/pipeline.js`: lines **1–30** are sidebar `.pl-stage` helpers (`plMeta/plState/plActivate/plMark/plReset/plStatus/log`) used by `agent.js` and the visible **Pipeline** card (`_app_left.html:51-100`) — **KEEP**. Lines **32–397** are the `PL2` overlay IIFE — **DELETE**.
- External `PL2` usage is only `PL2.start()` (`agent.js:93`) and `PL2.event(ev)` (`agent.js:212`). `templates/index.html.bak` is dead.
- The dashboard is the current view when `#go` is clicked (button lives in the app view), so removing the overlay reveals a live-building dashboard immediately.
- `renderClusters(cs)` (`clusters.js:2-31`) does `clearNode($("#clusters"))` then rebuilds every card on each call. Called from `labeled` and `reranked` in `handle()`.
- Cluster shape: `{ id, label, n, sentiment:{pos,neu,neg} }`.
- `#clusters` is at `_app_right.html:27`; `#graphHint` at `:16`; `#voices` panel hidden by default, shown in `fillVoices` (`clusters.js:166`); `#evidence` shown in `renderEvidence` (`evidence.js:61`).
- `agent.js handle()` already: `posts_fetched`→`#m-posts`; `clustered`→`#m-clusters`/`#m-entropy`; `labeled`→`renderClusters`+`renderSentChart`; `reranked`→re-render; `done`→`drawGraph(rid)` (called in `subscribe`).
- `SOURCE_META`/`sourceMeta` live in `clusters.js`. `prefers-reduced-motion` checked via `window.matchMedia("(prefers-reduced-motion: reduce)").matches`.
- No JS test harness (pytest only). Verification = `node --check` + manual run.

---

## File Structure

- `static/js/pipeline.js` — delete the `PL2` IIFE; keep lines 1–30.
- `static/js/agent.js` — drop `PL2.start()`/`PL2.event(ev)`; on run start call `dashSkeleton()` + `resetTypedLabels()`; pass `{typed:true}` to `renderClusters` on `labeled`.
- `static/js/clusters.js` — add `typeText`, `_shownLabels` + `resetTypedLabels`, `dashSkeleton`; extend `renderClusters(cs, opts)` (typed labels, `dash-rise` on new cards, skeleton clear); `reveal` on voices.
- `static/js/evidence.js` — add `reveal` to the evidence panel.
- `static/css/animations.css` — append skeleton shimmer, typed caret, `dash-rise`, `reveal` styles.
- `templates/partials/_loader.html` — empty the overlay markup.

---

### Task 1: Remove the PL2 overlay

**Files:**
- Modify: `static/js/pipeline.js` (delete lines 32–397)
- Modify: `static/js/agent.js:93` and `agent.js:212`
- Modify: `templates/partials/_loader.html` (whole file)

- [ ] **Step 1: Delete the PL2 IIFE from pipeline.js**

In `static/js/pipeline.js`, delete everything from line 32 (the comment `/* ===================== Pipeline full-screen loader ===================== */`) through the end of the file (the closing `})();` of `const PL2 = (function () { ... })();`). Keep lines 1–30 (the sidebar `pl*` helpers) exactly as they are. The file now ends at line 30 (`function log(_msg, _cls) {}`).

- [ ] **Step 2: Remove the PL2.start call in agent.js**

In `static/js/agent.js`, in `start()`, delete the line:

```javascript
  PL2.start();
```

- [ ] **Step 3: Remove the PL2.event call in agent.js**

In `static/js/agent.js`, in `handle(ev)`, delete the first line of the function body:

```javascript
  PL2.event(ev);
```

(so `handle(ev)` now begins directly with `switch (ev.type) {`).

- [ ] **Step 4: Empty the overlay markup**

Replace the entire contents of `templates/partials/_loader.html` with a single comment so the include stays valid but renders nothing:

```html
{# loader overlay removed — dashboard now builds live (see realtime spec) #}
```

- [ ] **Step 5: Syntax check**

Run: `node --check static/js/pipeline.js && node --check static/js/agent.js`
Expected: no output (exit 0).

- [ ] **Step 6: Commit**

```bash
git add static/js/pipeline.js static/js/agent.js templates/partials/_loader.html
git commit -m "feat(realtime): remove blocking loader overlay, reveal live dashboard"
```

---

### Task 2: Skeleton + typed-label cluster rendering

**Files:**
- Modify: `static/js/clusters.js` (add helpers above `renderClusters`; rewrite `renderClusters`)
- Modify: `static/js/agent.js` (`start()` + `handle()` `labeled`/`reranked`/`started`)
- Modify: `static/css/animations.css` (append styles)

- [ ] **Step 1: Add typed-label + skeleton helpers to clusters.js**

In `static/js/clusters.js`, insert this block immediately **before** `function renderClusters(cs) {` (before line 2):

```javascript
/* realtime build: typed labels + skeleton placeholders */
let _shownLabels = new Set();
function resetTypedLabels() { _shownLabels = new Set(); }

function typeText(node, text, speed) {
  const rm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (rm || !text) { node.textContent = text || ""; return; }
  node.textContent = "";
  node.classList.add("typing");
  let i = 0;
  const t = setInterval(() => {
    node.textContent = text.slice(0, ++i);
    if (i >= text.length) { clearInterval(t); node.classList.remove("typing"); }
  }, speed || 26);
}

function dashSkeleton() {
  const el = $("#clusters"); if (!el) return;
  clearNode(el);
  for (let i = 0; i < 3; i++) {
    el.appendChild(elem("div", { class: "cluster skel" },
      elem("div", { class: "skel-line w60" }),
      elem("div", { class: "skel-bar" })));
  }
  const hint = $("#graphHint");
  if (hint) { hint.classList.remove("hidden");
    hint.textContent = "Building the graph as posts come in…"; }
}
```

- [ ] **Step 2: Rewrite renderClusters to support typed/new-card animation**

In `static/js/clusters.js`, replace the existing `renderClusters` function (lines 2–31) with:

```javascript
function renderClusters(cs, opts) {
  const typed = !!(opts && opts.typed);
  const el = $("#clusters");
  clearNode(el);
  const sorted = cs.slice().sort((a, b) => b.n - a.n);
  for (const c of sorted) {
    const s = c.sentiment || { pos: 0, neu: 1, neg: 0 };
    const pos = Math.round(s.pos * 100);
    const neg = Math.round(s.neg * 100);
    const neu = Math.max(0, 100 - pos - neg);
    const label = String(c.label || "General discussion");
    const isNew = typed && !_shownLabels.has(label);
    if (isNew) _shownLabels.add(label);
    const b = elem("b");
    if (isNew) typeText(b, label); else b.textContent = label;
    const card = elem("div", { class: "cluster clickable" + (isNew ? " dash-rise" : ""),
        "data-cid": String(c.id), role: "button", tabindex: "0",
        "aria-label": "Explore posts in " + label },
      elem("div", { class: "hd" },
        b,
        elem("span", { class: "pill" }, c.n + " posts"),
      ),
      elem("div", { class: "bar" },
        elem("span", { class: "pos", style: "width:" + pos + "%" }),
        elem("span", { class: "neu", style: "width:" + neu + "%" }),
        elem("span", { class: "neg", style: "width:" + neg + "%" }),
      ),
      elem("div", { class: "hint" }, "Click to read the posts behind this →"),
    );
    card.addEventListener("click", () => openClusterDrawer(c.id));
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openClusterDrawer(c.id); }
    });
    el.appendChild(card);
  }
}
```

- [ ] **Step 3: Wire run start + typed labeled in agent.js**

In `static/js/agent.js`, in `start()`, find the block (around lines 90–93):

```javascript
  plReset();
  plActivate("seed");
  plStatus("Run starting…");
```

and add two lines after it:

```javascript
  plReset();
  plActivate("seed");
  plStatus("Run starting…");
  resetTypedLabels();
  dashSkeleton();
```

- [ ] **Step 4: Pass typed:true on labeled, keep reranked instant**

In `static/js/agent.js`, in `handle()`, change the `labeled` case so the first render types in new labels:

```javascript
    case "labeled":
      renderClusters(ev.clusters || [], { typed: true });
      renderSentChart(ev.clusters || []);
      plMark("cluster", "done");
      plActivate("label");
      plMeta("label", (ev.clusters || []).length + " clusters named");
      break;
```

Leave the `reranked` case as-is (`renderClusters(ev.clusters)` — instant update, existing labels won't re-type because they're already in `_shownLabels`).

- [ ] **Step 5: Append CSS for skeleton + typed caret + rise**

Append to the end of `static/css/animations.css`:

```css
/* ===================== Realtime dashboard build ===================== */
.cluster.skel { pointer-events: none; }
.skel-line, .skel-bar { border-radius: 6px;
  background: linear-gradient(90deg,
    color-mix(in srgb, var(--muted) 12%, transparent) 25%,
    color-mix(in srgb, var(--muted) 22%, transparent) 37%,
    color-mix(in srgb, var(--muted) 12%, transparent) 63%);
  background-size: 400% 100%; animation: dash-shimmer 1.4s ease infinite; }
.skel-line { height: 14px; margin-bottom: 10px; }
.skel-line.w60 { width: 60%; }
.skel-bar { height: 10px; width: 100%; }
@keyframes dash-shimmer { 0% { background-position: 100% 0; } 100% { background-position: 0 0; } }
.cluster .hd b.typing::after { content: "▍"; color: var(--accent2);
  animation: dash-caret 0.9s steps(1) infinite; }
@keyframes dash-caret { 50% { opacity: 0; } }
.dash-rise { animation: dash-rise-kf 0.4s cubic-bezier(0.16, 1, 0.3, 1) both; }
@keyframes dash-rise-kf { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) {
  .dash-rise { animation: none; }
  .skel-line, .skel-bar { animation: none; }
}
```

- [ ] **Step 6: Syntax check**

Run: `node --check static/js/clusters.js && node --check static/js/agent.js`
Expected: no output (exit 0).

- [ ] **Step 7: Commit**

```bash
git add static/js/clusters.js static/js/agent.js static/css/animations.css
git commit -m "feat(realtime): skeleton placeholders + typed-in talking points"
```

---

### Task 3: Reveal animation on voices & evidence panels

**Files:**
- Modify: `static/js/clusters.js:166` (`fillVoices`)
- Modify: `static/js/evidence.js:61` (`renderEvidence`)
- Modify: `static/css/animations.css` (append `reveal` style)

- [ ] **Step 1: Reveal the voices panel**

In `static/js/clusters.js`, in `fillVoices`, find:

```javascript
  $("#voices").style.display = "";
```

and change it to:

```javascript
  $("#voices").style.display = "";
  $("#voices").classList.add("reveal");
```

- [ ] **Step 2: Reveal the evidence panel**

In `static/js/evidence.js`, in `renderEvidence`, find:

```javascript
  $("#evidence").style.display = "";
```

and change it to:

```javascript
  $("#evidence").style.display = "";
  $("#evidence").classList.add("reveal");
```

- [ ] **Step 3: Append the reveal CSS**

Append to the end of `static/css/animations.css`:

```css
.reveal { animation: dash-reveal 0.5s cubic-bezier(0.16, 1, 0.3, 1) both; }
@keyframes dash-reveal { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) { .reveal { animation: none; } }
```

- [ ] **Step 4: Syntax check**

Run: `node --check static/js/clusters.js && node --check static/js/evidence.js`
Expected: no output (exit 0).

- [ ] **Step 5: Commit**

```bash
git add static/js/clusters.js static/js/evidence.js static/css/animations.css
git commit -m "feat(realtime): fade-in reveal for voices & evidence panels"
```

---

### Task 4: Manual verification

**Files:** none (verification only).

- [ ] **Step 1: Run the app locally**

```bash
.venv/bin/python server.py
```
Open `http://localhost:5000`, sign in, run a topic with **Reddit + Hacker News** (fast, reliable from any IP).

- [ ] **Step 2: Observe the live build**

Confirm, with NO full-screen overlay:
- The dashboard is visible immediately; the **Pipeline** card shows the active stage and `#m-posts` starts at 0.
- The **Main talking points** panel shows 3 shimmering skeleton rows before data.
- `#m-posts` climbs in real time as `posts_fetched` events arrive.
- The sentiment chart draws/updates on `labeled`.
- Each new talking point **types in** character-by-character and its card rises in; on the final `reranked` the cards update (sentiment %) without re-typing or flicker.
- At completion the topic graph renders; voices/evidence panels fade in.

- [ ] **Step 3: Reduced-motion check**

In the browser devtools, emulate `prefers-reduced-motion: reduce`, run again, and confirm labels appear instantly (no typing) and panels appear without animation — everything still populates correctly.

- [ ] **Step 4: Cross-check against the event log**

In the server console, confirm the dashboard updates correspond to the actual emitted events (`seeded`, `posts_fetched`, `clustered`, `labeled`, `reranked`, `done`) — results are live, not batched at the end.

---

## Self-Review

**Spec coverage:**
- Remove blocking overlay → Task 1 (delete IIFE, drop calls, empty markup). ✓
- Dashboard builds live (KPIs/charts/graph) → already in `handle()`, now visible after Task 1; verified in Task 4. ✓
- Opinions/talking points stream in with typed effect → Task 2 (`typeText` + `renderClusters {typed}` + `_shownLabels` gating). ✓
- New cards animate, existing update instantly (no flicker/re-type) → Task 2 `isNew` gating via `_shownLabels`, reset per run. ✓
- Skeleton placeholders before first data → Task 2 `dashSkeleton()` + CSS shimmer; graph hint live copy. ✓
- Panel reveal (voices/evidence) → Task 3. ✓
- `prefers-reduced-motion` instant fallback → Task 2/Task 3 CSS media queries + `typeText` early return. ✓
- No backend / SSE-schema change; token-streaming deferred → respected (only presentation files touched). ✓
- Testing caveat (node --check + manual) → Task steps + Task 4. ✓

**Placeholder scan:** No TBD/TODO/"add error handling"/"similar to" — every code step is complete. ✓

**Type consistency:** `renderClusters(cs, opts)` with `opts.typed`; `typeText(node, text, speed)`; `_shownLabels` Set + `resetTypedLabels()`; `dashSkeleton()`; CSS classes `skel/skel-line/skel-bar/dash-rise/typing/reveal` consistent across Tasks 2–3. `resetTypedLabels`/`dashSkeleton` are defined in `clusters.js` and called from `agent.js` — both load before any run event fires (script order in `index.html`), so the references resolve. ✓
