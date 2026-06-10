/* pipeline stage indicators + full-screen loader (PL2) */
const PL_ORDER = ["seed", "fetch", "cluster", "label", "brief"];
const plEl = (s) => document.querySelector(`.pl-stage[data-stage="${s}"]`);
function plMeta(s, txt) {
  const el = plEl(s); if (!el) return;
  const m = el.querySelector("[data-meta]"); if (m) m.textContent = txt;
}
function plState(s, state) {
  const el = plEl(s); if (!el) return;
  el.classList.remove("active", "done", "err");
  if (state) el.classList.add(state);
}
function plActivate(stage) {
  for (const s of PL_ORDER) {
    if (s === stage) plState(s, "active");
    else if (PL_ORDER.indexOf(s) < PL_ORDER.indexOf(stage)) plState(s, "done");
  }
}
function plMark(stage, state) { plState(stage, state); }
function plReset() {
  for (const s of PL_ORDER) {
    plState(s, null);
    plMeta(s, "idle");
  }
  const v = $("#voices"); if (v) v.style.display = "none";
  if (_vTimer) { clearInterval(_vTimer); _vTimer = null; }
}
function plStatus(_t) {}

function log(_msg, _cls) {}

/* ===================== Pipeline full-screen loader ===================== */
const PL2 = (function () {
  const h = elem;
  const STAGES = [
    { label: "Got your question",            sub: "We've got what you're looking for — getting started." },
    { label: "Searching the internet",       sub: "Collecting posts, comments and discussions from across social media." },
    { label: "Reading through everything",   sub: "Going through each post to understand what people are saying." },
    { label: "Figuring out how people feel", sub: "Sorting posts into positive, mixed and negative." },
    { label: "Finding the main talking points", sub: "Grouping similar posts to see which topics keep coming up." },
    { label: "Putting your report together", sub: "Almost done — writing up what we found so it's easy to read." },
    { label: "Your results are ready!",      sub: "Here's everything we found. Take your time exploring." },
  ];
  const APPROX = [1, 14, 10, 7, 8, 20];
  const FINAL_MICRO = [
    "Pulling out the key themes…",
    "Weighing the strongest points on each side…",
    "Checking which views are best supported…",
    "Writing your plain-language summary…",
    "Polishing the wording so it's easy to read…",
  ];
  const REASSURE = [
    "We anonymise usernames — we only show what people said, not who.",
    "The more posts we find, the more reliable the results.",
    "Results cover the last 30 days of posts by default.",
    "We check Reddit, Hacker News, Facebook and more — all in one go.",
  ];
  const rm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let cur = -1, count = 0, plats = {}, finished = false, themeCount = 0;
  let simTimer = null, chainTimer = null, chainTimer2 = null, reassureTimer = null,
      etaTimer = null, animTimer = null, finalTimer = null, reassureIdx = 0, finalIdx = 0;

  const el = (id) => document.getElementById(id);

  function buildRail() {
    const r = el("pl2-rail"); clearNode(r);
    STAGES.forEach((s, i) => {
      const step = h("div", { class: "pl2-step", "data-i": String(i) },
        h("div", { class: "pl2-dot" }, String(i + 1)),
        h("div", { class: "pl2-lbl" }, s.label));
      r.appendChild(step);
      if (i < 6) r.appendChild(h("div", { class: "pl2-seg" }));
    });
    r.appendChild(h("div", { class: "pl2-eta", id: "pl2-eta" }));
    r.appendChild(h("div", { class: "pl2-reassure", id: "pl2-reassure" }));
    const a = h("a", { tabindex: "0" }, "Cancel and start over");
    a.addEventListener("click", confirmCancel);
    r.appendChild(h("div", { class: "pl2-cancel" }, a));
  }

  function paintRail() {
    document.querySelectorAll("#pl2-rail .pl2-step").forEach((step) => {
      const i = +step.dataset.i;
      step.classList.toggle("done", i < cur);
      step.classList.toggle("active", i === cur);
    });
    document.querySelectorAll("#pl2-rail .pl2-seg").forEach((seg, i) => seg.classList.toggle("done", i < cur));
  }

  function tickEta() {
    const eta = el("pl2-eta"); if (!eta) return;
    let left = 0;
    for (let i = Math.max(cur, 0); i < APPROX.length; i++) left += APPROX[i];
    eta.textContent = left <= 0 ? "Finishing up…"
      : left < 10 ? "Almost there…" : "About " + left + " seconds left";
  }

  function setStage(i) {
    if (finished || i <= cur || i > 6) return;
    cur = i; paintRail(); tickEta();
    el("pl2-h").textContent = STAGES[i].label;
    el("pl2-sub").textContent = STAGES[i].sub;
    renderAnim(i);
  }
  function setMin(i) { if (i > cur) setStage(i); }
  function clearAnim() {
    if (animTimer) { clearInterval(animTimer); clearTimeout(animTimer); animTimer = null; }
    if (finalTimer) { clearInterval(finalTimer); finalTimer = null; }
  }

  function renderAnim(i) {
    clearAnim();
    const a = el("pl2-anim"); clearNode(a);
    if (i === 0) {
      a.appendChild(h("div", { class: "pl2-check" },
        h("span", { class: "ring" }), h("span", { class: "ring" }),
        h("span", { class: "mk" }, "✓")));
    } else if (i === 1) {
      const solar = h("div", { class: "pl2-solar" }, h("div", { class: "pl2-globe" }, "🌐"));
      const sats = [
        ["", "🟠", "top:4%;left:50%"], ["", "🔵", "top:96%;left:50%"],
        ["rev", "🟧", "top:50%;left:4%"], ["rev", "🔴", "top:50%;left:96%"],
      ];
      const o1 = h("div", { class: "pl2-orbit" }), o2 = h("div", { class: "pl2-orbit rev" });
      sats.forEach(s => (s[0] ? o2 : o1).appendChild(h("div", { class: "pl2-sat", style: s[2] }, s[1])));
      solar.appendChild(o1); solar.appendChild(o2);
      a.appendChild(h("div", { style: "text-align:center" }, solar,
        h("div", { class: "pl2-count", id: "pl2-count" }, "0"),
        h("div", { class: "muted", style: "font-size:13px" }, "posts found so far"),
        h("div", { class: "pl2-chips", id: "pl2-chips" })));
      paintCount();
    } else if (i === 2) {
      const stack = h("div", { class: "pl2-cards" });
      ["pc1", "pc2", "pc3"].forEach(cl => stack.appendChild(
        h("div", { class: "pc " + cl }, h("div", { class: "l" }), h("div", { class: "l" }), h("div", { class: "l" }))));
      a.appendChild(h("div", { style: "display:flex;flex-direction:column;align-items:center;width:100%" },
        stack, h("div", { class: "pl2-bar" }, h("i", { id: "pl2-readbar" })),
        h("div", { class: "muted", style: "font-size:13px;margin-top:8px" }, "Reading posts…")));
      let p = 0; const bar = el("pl2-readbar");
      if (!rm) animTimer = setInterval(() => { p = Math.min(85, p + 7); if (bar) bar.style.width = p + "%"; }, 350);
      else if (bar) bar.style.width = "85%";
    } else if (i === 3) {
      const cols = [["pos", "Positive 😊"], ["neu", "Mixed 😐"], ["neg", "Negative 😞"]];
      const wrap = h("div", { class: "pl2-cols" });
      for (const c of cols) wrap.appendChild(h("div", { class: "pl2-col", id: "pl2c-" + c[0] }, h("div", { class: "lab" }, c[1])));
      a.appendChild(wrap);
      if (!rm) animTimer = setInterval(() => {
        const c = cols[Math.floor(Math.random() * 3)][0];
        const col = el("pl2c-" + c);
        if (col && col.children.length < 9) col.appendChild(h("div", { class: "pl2-pip " + c, style: "background:var(--" + c + ")" }));
      }, 140);
    } else if (i === 4) {
      animGalaxy(a);
    } else if (i === 5) {
      a.appendChild(h("div", { style: "display:flex;flex-direction:column;align-items:center;width:100%" },
        h("div", { class: "pl2-doc", id: "pl2-doc" }),
        h("div", { class: "muted", id: "pl2-final-status",
          style: "font-size:13px;margin-top:14px;min-height:18px;transition:opacity .3s;text-align:center" })));
      typeDoc();
      startFinalStatus();
    }
  }

  function startFinalStatus() {
    finalIdx = 0;
    const tick = () => {
      const s = el("pl2-final-status"); if (!s) return;
      s.style.opacity = "0";
      setTimeout(() => {
        if (!el("pl2-final-status")) return;
        const lead = (finalIdx === 0 && themeCount)
          ? "Found " + themeCount + " main talking points — writing them up…"
          : FINAL_MICRO[finalIdx % FINAL_MICRO.length];
        s.textContent = lead; finalIdx++; s.style.opacity = "1";
      }, 250);
    };
    tick();
    if (!rm) finalTimer = setInterval(tick, 2600);
  }

  function animGalaxy(a) {
    const box = h("div", { class: "pl2-galaxy", id: "pl2-galaxy" });
    const clusters = [
      { c: "var(--neg)", nm: "Cost concerns" },
      { c: "var(--accent2)", nm: "Safety questions" },
      { c: "var(--pos)", nm: "Personal stories" },
    ];
    clusters.forEach((cl) => {
      box.appendChild(h("div", { class: "pl2-cl", style: "color:" + cl.c },
        h("div", { class: "pl2-pearl" }, h("span", { class: "pl2-moon" })),
        h("div", { class: "nm" }, cl.nm)));
    });
    a.appendChild(box);
  }

  function paintCount() {
    const c = el("pl2-count"); if (c) c.textContent = count;
    // Persistent live tally in pl2-extra — the stage-1 "pl2-count" element is
    // destroyed when the anim advances (~14s), but fetches (esp. slow FB runs)
    // land minutes later. This badge survives stage swaps so the number climbs.
    const extra = el("pl2-extra");
    if (extra) {
      let live = el("pl2-livecount");
      if (!live && count > 0) {
        live = h("div", { id: "pl2-livecount", style:
          "margin-top:10px;text-align:center;font-size:14px;font-weight:600;color:var(--muted,#94a3b8)" });
        extra.appendChild(live);
      }
      if (live) live.textContent = "🔎 " + count + " posts found so far";
    }
    const chips = el("pl2-chips"); if (!chips) return;
    clearNode(chips);
    for (const k in plats) {
      if (!plats[k]) continue;
      const m = sourceMeta(k);
      chips.appendChild(h("span", { class: "pl2-chip" }, m.icon + " " + m.label + " " + plats[k]));
    }
  }

  function typeDoc() {
    const doc = el("pl2-doc"); if (!doc) return;
    const heads = ["The Short Version", "What's This Actually About?", "Do Most People Agree?", "Our Take"];
    let n = 0;
    function next() {
      if (finished || !document.body.contains(doc)) return;
      if (n >= heads.length) {  // loop so the final stage never looks frozen
        if (!rm) animTimer = setTimeout(() => { clearNode(doc); n = 0; next(); }, 1600);
        return;
      }
      doc.appendChild(h("h5", null, heads[n]));
      for (let k = 0; k < 2; k++) {
        const ln = h("div", { class: "ln" }); doc.appendChild(ln);
        setTimeout(() => { ln.style.width = (60 + Math.random() * 30) + "%"; }, 100 + k * 120);
      }
      n++; if (!rm) animTimer = setTimeout(next, 900);
    }
    next();
  }

  function rotateReassure() {
    const re = el("pl2-reassure"); if (!re) return;
    re.style.opacity = "0";
    setTimeout(() => { re.textContent = REASSURE[reassureIdx % REASSURE.length]; reassureIdx++; re.style.opacity = "1"; }, 300);
  }

  function spawnParticles() {
    if (rm) return;
    const host = el("pl2-particles"); if (!host) return;
    for (let i = 0; i < 6; i++) {
      const sz = 4 + Math.random() * 3;
      host.appendChild(h("div", { class: "pl2-particle", style:
        "width:" + sz + "px;height:" + sz + "px;left:" + (Math.random() * 100) + "%;" +
        "animation-duration:" + (9 + Math.random() * 6) + "s;animation-delay:" + (Math.random() * 9) + "s" }));
    }
  }

  function startSim() {
    let i = 1, acc = 0;
    if (simTimer) clearInterval(simTimer);
    simTimer = setInterval(() => { acc += 1; if (i < 6 && acc >= APPROX[i]) { acc = 0; setMin(i); i++; } }, 1000);
  }

  function start() {
    finished = false; cur = -1; count = 0; plats = {}; themeCount = 0; finalIdx = 0;
    buildRail();
    el("pl2").classList.add("open");
    clearNode(el("pl2-particles"));
    clearNode(el("pl2-extra"));
    spawnParticles();
    setStage(0);
    setTimeout(() => setMin(1), 700);
    rotateReassure();
    reassureTimer = setInterval(rotateReassure, 8000);
    etaTimer = setInterval(tickEta, 5000);
    startSim();
  }

  function event(ev) {
    if (!el("pl2").classList.contains("open")) return;
    switch (ev.type) {
      case "started": case "seeded": case "iter_start": setMin(1); break;
      case "posts_fetched":
        setMin(1);
        if (ev.n_total != null) count = ev.n_total;
        if (ev.source) plats[ev.source] = (plats[ev.source] || 0) + (ev.n_new || 0);
        paintCount();
        break;
      case "clustered":
        setMin(2);
        clearTimeout(chainTimer); clearTimeout(chainTimer2);
        chainTimer = setTimeout(() => setMin(3), 1400);
        chainTimer2 = setTimeout(() => setMin(4), 2800);
        break;
      case "labeled":
        if (ev.clusters && ev.clusters.length) themeCount = ev.clusters.length;
        setMin(5); break;
      case "briefing_ready": case "evidence_ready": setMin(5); break;
      case "embed_error": fail("while sorting the posts into groups"); break;
      case "briefing_error": briefingFailed(); break;
      case "error": fail("while gathering your results"); break;
      case "done": complete(); break;
    }
  }

  function stopTimers() {
    [simTimer, chainTimer, chainTimer2, reassureTimer, etaTimer, animTimer, finalTimer].forEach(t => {
      if (t) { clearInterval(t); clearTimeout(t); } });
    simTimer = chainTimer = chainTimer2 = reassureTimer = etaTimer = animTimer = finalTimer = null;
  }

  function complete() {
    if (finished) return; finished = true;
    cur = 6; paintRail();
    el("pl2-h").textContent = STAGES[6].label;
    el("pl2-sub").textContent = STAGES[6].sub;
    clearAnim(); const a = el("pl2-anim"); clearNode(a);
    a.appendChild(h("div", { style: "font-size:90px" }, "🎉"));
    confetti();
    setTimeout(() => { el("pl2").classList.remove("open"); stopTimers(); }, 1400);
  }

  function confetti() {
    if (rm) return;
    const host = el("pl2-particles");
    const cols = ["#10b981", "#6ee7b7", "#94a3b8", "#fbbf24", "#f87171"];
    for (let i = 0; i < 24; i++) {
      const c = h("div", { class: "pl2-confetti", style:
        "left:" + (20 + Math.random() * 60) + "%;background:" + cols[i % cols.length] +
        ";animation-delay:" + (Math.random() * 0.3) + "s" });
      host.appendChild(c);
      setTimeout(() => c.remove(), 1600);
    }
  }

  function fail(where) {
    if (finished) return; finished = true; stopTimers();
    document.querySelectorAll("#pl2-rail .pl2-step.active .pl2-dot").forEach(d => {
      d.textContent = "!"; d.style.background = "#f59e0b"; d.style.borderColor = "#f59e0b";
    });
    el("pl2-h").textContent = "Something went wrong";
    el("pl2-sub").textContent = "We hit a problem " + where + ". This sometimes happens — it's not your fault.";
    clearAnim(); const a = el("pl2-anim"); clearNode(a); a.appendChild(h("div", { style: "font-size:72px" }, "🔌"));
    const ex = el("pl2-extra"); clearNode(ex);
    const retry = h("button", null, "Try again");
    retry.addEventListener("click", () => { hide(); const g = $("#go"); if (g) g.click(); });
    const change = h("button", { class: "secondary" }, "Change my question");
    change.addEventListener("click", hide);
    ex.appendChild(h("div", { class: "pl2-err-actions" }, retry, change));
  }

  // PDF export is the very last step — by the time it can fail, every post,
  // cluster, sentiment score and the graph are already collected and live on
  // the dashboard. So this is NOT a workflow failure: reassure and route the
  // user straight to their results instead of the generic error screen.
  function briefingFailed() {
    if (finished) return; finished = true; stopTimers();
    cur = 6; paintRail();
    document.querySelectorAll("#pl2-rail .pl2-step .pl2-dot").forEach(d => {
      if (d.textContent === "" || d.textContent === "6") return;
    });
    el("pl2-h").textContent = "Your insights are ready";
    el("pl2-sub").textContent =
      "We collected everything and your dashboard is fully populated — only the " +
      "downloadable PDF export didn't generate. Nothing else was affected.";
    clearAnim(); const a = el("pl2-anim"); clearNode(a);
    a.appendChild(h("div", { style: "font-size:72px" }, "📊"));
    const ex = el("pl2-extra"); clearNode(ex);
    ex.appendChild(h("ul", { class: "pl2-recover-list" },
      h("li", null, "✓ Data collection succeeded"),
      h("li", null, "✓ Clusters, sentiment and the topic graph are ready"),
      h("li", null, "✓ The dashboard stays fully interactive"),
      h("li", { class: "muted" }, "✕ Only the PDF export failed")));
    const view = h("button", { class: "pl2-recover-btn" }, "View your dashboard →");
    view.addEventListener("click", hide);
    ex.appendChild(h("div", { class: "pl2-err-actions" }, view));
  }

  function partial(platform) {
    el("pl2-extra").appendChild(h("div", { class: "pl2-banner" },
      "We couldn't reach " + platform + ", so those posts aren't included. Everything else is fine."));
  }

  function confirmCancel() {
    const ex = el("pl2-extra"); clearNode(ex);
    const yes = h("button", { class: "secondary" }, "Yes, cancel"); yes.addEventListener("click", hide);
    const no = h("button", null, "Keep waiting"); no.addEventListener("click", () => clearNode(ex));
    ex.appendChild(h("p", { class: "muted", style: "font-size:13px" }, "Are you sure? We'll lose all progress."));
    ex.appendChild(h("div", { class: "pl2-err-actions" }, yes, no));
  }

  function hide() { finished = true; stopTimers(); el("pl2").classList.remove("open"); clearNode(el("pl2-extra")); }

  return { start, event, complete, fail, briefingFailed, partial, hide };
})();
