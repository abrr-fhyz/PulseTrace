/* boot wiring: global keydown, initial route, orchestration timeline. Loads LAST. */
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if ($("#cluster-drawer").classList.contains("open")) closeClusterDrawer();
  else if ($("#hist-drawer").classList.contains("open")) closeHistory();
});

routeFromHash();
updateAppBadge();

/* ── Orchestration (LangGraph) live timeline ─────────────────────────
   Driven by the main run's SSE stream (window.__orch.handle), so there is a
   single search box: the "Run Agent" form feeds /api/agent/run, which runs the
   full pipeline inside the graph and adds engagement alerting + retry/recovery. */
(function () {
  const $o = (id) => document.getElementById(id);
  const NODES = ["crawl", "score", "alert", "recover", "done"];

  const chip = (n) => document.querySelector('#orch-timeline .orch-node[data-node="' + n + '"]');
  const setInfo = (n, t) => { const c = chip(n); if (c) { const i = c.querySelector("[data-info]"); if (i && t != null) i.textContent = t; } };
  const activate = (n) => { const c = chip(n); if (c) c.classList.add("active"); };
  const settle = (n, cls) => { const c = chip(n); if (c) { c.classList.remove("active"); c.classList.add(cls); } };

  function begin() {
    NODES.forEach((n) => { const c = chip(n); if (c) { c.className = "orch-node"; setInfo(n, ""); } });
    $o("orch-result").style.display = "none";
    $o("orch-alerted").style.display = "none";
    activate("crawl");
  }

  function handle(m) {
    if (!m || !m.type) return;
    if (m.type === "orch_started") { begin(); return; }
    if (m.type === "orch_step") {
      const d = m.data || {};
      if (m.node === "crawl") { settle("crawl", d.error ? "err" : "done"); setInfo("crawl", (d.items || 0) + " items"); if (!d.error) activate("score"); }
      else if (m.node === "score") { settle("score", "done"); setInfo("score", "peak " + (d.peak != null ? Number(d.peak).toFixed(2) : "--")); activate(d.should_alert ? "alert" : "done"); }
      else if (m.node === "alert") { settle("alert", "warn"); setInfo("alert", "fired"); activate("done"); }
      else if (m.node === "recover") { settle("recover", "warn"); setInfo("recover", "retry " + (d.retry_count || 0)); activate("crawl"); }
      else if (m.node === "done") { settle("done", "done"); }
      return;
    }
    if (m.type === "orch_error") { settle("done", "err"); setInfo("done", "error"); return; }
    if (m.type === "orch_done") {
      const s = m.summary || {};
      $o("orch-items").textContent = s.n_items != null ? s.n_items : 0;
      $o("orch-peak").textContent = s.max_score != null ? Number(s.max_score).toFixed(2) : "--";
      $o("orch-retries").textContent = s.retry_count != null ? s.retry_count : 0;
      $o("orch-result").style.display = "grid";
      const a = $o("orch-alerted");
      if (s.error) { a.style.display = "block"; a.textContent = "Error: " + s.error; a.style.color = "var(--neg)"; }
      else if (s.alerted) { a.style.display = "block"; a.textContent = "⚡ Engagement threshold tripped — alert fired."; a.style.color = "var(--accent3)"; }
      else { a.style.display = "block"; a.textContent = (s.clusters || 0) + " clusters · no engagement alert"; a.style.color = "var(--muted)"; }
      settle("done", "done");
    }
  }

  window.__orch = { begin, handle };
})();
