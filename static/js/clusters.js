/* clusters list, cluster drawer, voices carousel */

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

const SOURCE_META = {
  reddit:     { icon: "🟠", label: "Reddit" },
  hn:         { icon: "🟧", label: "Hacker News" },
  hackernews: { icon: "🟧", label: "Hacker News" },
  facebook:   { icon: "🔵", label: "Facebook" },
  x:          { icon: "⚫", label: "X" },
  twitter:    { icon: "⚫", label: "Twitter / X" },
  instagram:  { icon: "🟣", label: "Instagram" },
  youtube:    { icon: "🔴", label: "YouTube" },
  polymarket: { icon: "🟦", label: "Polymarket" },
  github:     { icon: "⬛", label: "GitHub" },
  bluesky:    { icon: "🦋", label: "Bluesky" },
};
function sourceMeta(s) {
  return SOURCE_META[String(s || "").toLowerCase()] || { icon: "💬", label: s || "Web" };
}

function moodLabel(sent) {
  const s = sent || {};
  const pos = Number(s.pos) || 0, neg = Number(s.neg) || 0;
  if (pos > neg + 0.12) return "Most people feel good about this";
  if (neg > pos + 0.12) return "More people are unhappy than happy";
  return "People are pretty split on this";
}

function relTime(ts) {
  if (!ts) return "";
  const d = (Date.now() / 1000) - Number(ts);
  if (d < 3600) return Math.max(1, Math.round(d / 60)) + "m ago";
  if (d < 86400) return Math.round(d / 3600) + "h ago";
  return Math.round(d / 86400) + "d ago";
}

let _drawerPosts = [];
function openClusterDrawer(cid) {
  const drawer = $("#cluster-drawer"), backdrop = $("#cluster-backdrop");
  drawer.classList.add("open"); backdrop.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  $("#drawer-title").textContent = "Loading…";
  $("#drawer-why").textContent = "";
  $("#drawer-count").textContent = "";
  clearNode($("#drawer-body"));
  $("#drawer-search").value = "";
  if (!runId) return;
  fetch("/run/" + encodeURIComponent(runId) + "/cluster/" + encodeURIComponent(cid))
    .then(r => r.json())
    .then(fillDrawer)
    .catch(() => { $("#drawer-title").textContent = "Couldn't load this group"; });
}

function fillDrawer(d) {
  if (!d || d.error) { $("#drawer-title").textContent = "Couldn't load this group"; return; }
  const s = d.sentiment || { pos: 0, neu: 1, neg: 0 };
  const pos = Math.round((s.pos || 0) * 100), neg = Math.round((s.neg || 0) * 100);
  const neu = Math.max(0, 100 - pos - neg);
  const color = pos > neg ? "var(--pos)" : neg > pos ? "var(--neg)" : "var(--neu)";
  $("#drawer-strip").style.background = color;
  $("#drawer-title").textContent = d.label || "Topic";
  $("#drawer-why").textContent = d.desc
    ? "Why these are grouped: " + d.desc
    : "These posts were grouped together because they talk about the same thing in similar ways.";
  const mood = $("#drawer-mood"); clearNode(mood);
  mood.appendChild(elem("span", { class: "pos", style: "width:" + pos + "%" }));
  mood.appendChild(elem("span", { class: "neu", style: "width:" + neu + "%" }));
  mood.appendChild(elem("span", { class: "neg", style: "width:" + neg + "%" }));
  $("#drawer-mood-lbl").textContent = moodLabel(s) + " · 😊 " + pos + "%  😐 " + neu + "%  😞 " + neg + "%";
  $("#drawer-count").textContent = "Found in " + (d.n || 0) + " post" + (d.n === 1 ? "" : "s");
  _drawerPosts = d.posts || [];
  paintDrawerPosts("");
}

function paintDrawerPosts(filter) {
  const body = $("#drawer-body"); clearNode(body);
  const q = (filter || "").toLowerCase();
  const list = q
    ? _drawerPosts.filter(p => (p.text || "").toLowerCase().includes(q))
    : _drawerPosts;
  if (!list.length) {
    body.appendChild(elem("div", { class: "drawer-empty" },
      _drawerPosts.length ? "No posts match your search."
                          : "We're still gathering posts for this group. Check back soon."));
    return;
  }
  for (const p of list) {
    const m = sourceMeta(p.source);
    const meta = elem("div", { class: "meta" },
      elem("span", { class: "src" }, m.icon + " " + m.label),
      p.author ? elem("span", null, "· " + String(p.author)) : null,
      p.ts ? elem("span", null, "· " + relTime(p.ts)) : null,
    );
    const foot = elem("div", { class: "foot" });
    if (p.reactions) foot.appendChild(elem("span", null, "👍 " + p.reactions + " liked this"));
    if (p.comments) foot.appendChild(elem("span", null, "💬 " + p.comments));
    if (p.url) {
      const a = elem("a", { href: p.url, target: "_blank", rel: "noopener" }, "See original →");
      foot.appendChild(a);
    }
    body.appendChild(elem("div", { class: "post-card" },
      meta,
      elem("div", { class: "txt" }, String(p.text || "")),
      foot,
    ));
  }
}

function closeClusterDrawer() {
  $("#cluster-drawer").classList.remove("open");
  $("#cluster-backdrop").classList.remove("open");
  $("#cluster-drawer").setAttribute("aria-hidden", "true");
}
$("#drawer-close").addEventListener("click", closeClusterDrawer);
$("#cluster-backdrop").addEventListener("click", closeClusterDrawer);
$("#drawer-search").addEventListener("input", (e) => paintDrawerPosts(e.target.value));

const BUCKET_EMOJI = { pos: "😊", neu: "😐", neg: "😞" };
const BUCKET_WHY = {
  pos: "A clearly positive take",
  neu: "A balanced or factual point",
  neg: "A strongly critical view",
};
const _reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let _voices = [], _vIdx = 0, _vTimer = null;

function loadVoices() {
  if (!runId) return;
  fetch("/run/" + encodeURIComponent(runId) + "/voices")
    .then(r => r.json())
    .then(fillVoices)
    .catch(() => {});
}

function fillVoices(d) {
  if (!d || (!(d.voices || []).length && !(d.notable || []).length)) return;
  $("#voices").style.display = "";

  const s = d.sentiment || { pos: 0, neu: 1, neg: 0 };
  const pos = Math.round((s.pos || 0) * 100), neg = Math.round((s.neg || 0) * 100);
  const neu = Math.max(0, 100 - pos - neg);
  const mb = $("#voices-mood"); clearNode(mb);
  mb.appendChild(elem("span", { class: "pos", style: "width:" + pos + "%" }));
  mb.appendChild(elem("span", { class: "neu", style: "width:" + neu + "%" }));
  mb.appendChild(elem("span", { class: "neg", style: "width:" + neg + "%" }));
  $("#voices-mood-lbl").textContent = "";
  $("#voices-mood-lbl").appendChild(document.createTextNode(moodLabel(s) + " "));
  $("#voices-mood-lbl").appendChild(elem("small", null,
    "(😊 " + pos + "% liked it · 😐 " + neu + "% mixed · 😞 " + neg + "% didn't)"));

  const themes = (d.themes || []).filter(Boolean);
  $("#voices-why").textContent = themes.length
    ? "People are mostly reacting to " + joinPlain(themes) + "."
    : "Here's a sample of what people are actually posting.";

  _voices = d.voices || [];
  _vIdx = 0;
  buildDots();
  showVoice(0);
  if (_vTimer) clearInterval(_vTimer);
  if (!_reduceMotion && _voices.length > 1) {
    _vTimer = setInterval(() => showVoice(_vIdx + 1), 5500);
  }

  const nb = $("#voices-notable"); clearNode(nb);
  for (const v of (d.notable || [])) {
    const why = BUCKET_WHY[v.bucket] || "Worth a look";
    const item = elem("div", { class: "notable-item " + (v.bucket || "neu") },
      elem("div", { class: "nq" }, "“" + truncate(v.text, 160) + "”"),
      elem("div", { class: "nwhy" },
        why + " · about " + (v.cluster || "this topic") + " ",
        v.url ? elem("a", { href: v.url, target: "_blank", rel: "noopener" }, "[View post →]") : null),
    );
    nb.appendChild(item);
  }
  if (!nb.firstChild) nb.appendChild(elem("p", { class: "ev-intro" }, "No standout reactions yet."));
}

function joinPlain(arr) {
  if (arr.length === 1) return arr[0];
  if (arr.length === 2) return arr[0] + " and " + arr[1];
  return arr.slice(0, -1).join(", ") + ", and " + arr[arr.length - 1];
}
function truncate(t, n) {
  t = String(t || "");
  return t.length > n ? t.slice(0, n).trimEnd() + "…" : t;
}

function showVoice(i) {
  if (!_voices.length) return;
  _vIdx = (i + _voices.length) % _voices.length;
  const v = _voices[_vIdx];
  const m = sourceMeta(v.source);
  const stage = $("#car-stage"); clearNode(stage);
  const meta = elem("div", { class: "vmeta" },
    elem("span", { class: "vbadge " + (v.bucket || "neu") },
      (BUCKET_EMOJI[v.bucket] || "💬") + " " + (v.bucket === "pos" ? "positive" : v.bucket === "neg" ? "negative" : "mixed")),
    elem("span", { class: "src" }, m.icon + " " + m.label),
    v.ts ? elem("span", null, "· " + relTime(v.ts)) : null,
    v.url ? elem("a", { href: v.url, target: "_blank", rel: "noopener" }, "View post →") : null,
  );
  stage.appendChild(elem("div", { class: "voice-card" },
    elem("div", { class: "vq" }, "“" + truncate(v.text, 220) + "”"),
    meta,
  ));
  document.querySelectorAll("#car-dots .dot").forEach((d, k) => d.classList.toggle("on", k === _vIdx));
}

function buildDots() {
  const dots = $("#car-dots"); clearNode(dots);
  _voices.forEach((_, k) => {
    const d = elem("div", { class: "dot" + (k === 0 ? " on" : "") });
    d.addEventListener("click", () => { showVoice(k); resetVoiceTimer(); });
    dots.appendChild(d);
  });
}
function resetVoiceTimer() {
  if (_vTimer) clearInterval(_vTimer);
  if (!_reduceMotion && _voices.length > 1) _vTimer = setInterval(() => showVoice(_vIdx + 1), 5500);
}
$("#car-prev").addEventListener("click", () => { showVoice(_vIdx - 1); resetVoiceTimer(); });
$("#car-next").addEventListener("click", () => { showVoice(_vIdx + 1); resetVoiceTimer(); });
