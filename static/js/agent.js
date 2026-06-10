/* app view controller, run lifecycle, SSE stream, replay */
function onEnterApp() {
  updateAppBadge();
  loadHistory();
  // Restore ONLY when an explicit run was referenced (chat-back / history click).
  // A plain refresh has no ref → fresh dashboard.
  if (_bootRunId) {
    const rid = _bootRunId; _bootRunId = null;
    if (location.hash !== "#/app") history.replaceState(null, "", "#/app");
    restoreRun(rid);
  }
}

// Wipe the dashboard back to a clean slate for a new search.
function blankDashboard() {
  runId = null;
  $("#topic").value = "";
  $("#opinion").value = "";
  clearNode($("#clusters"));
  if (sentChart) { sentChart.destroy(); sentChart = null; }
  if (cy) { cy.destroy(); cy = null; }
  { const h = $("#graphHint"); if (h) h.classList.remove("hidden"); }
  $("#m-posts").textContent = "0";
  $("#m-clusters").textContent = "0";
  { const e = $("#m-entropy"); if (e) e.textContent = "0.00"; }
  $("#voices").style.display = "none";
  $("#evidence").style.display = "none";
  const bl = $("#briefing-link"); bl.style.display = "none"; bl.href = "#";
  document.querySelectorAll("#history-list .hist-row.active")
    .forEach(r => r.classList.remove("active"));
}

async function start() {
  const topic = $("#topic").value.trim();
  if (!topic) return;
  const sources = [];
  if ($("#src-reddit").checked) sources.push("reddit");
  if ($("#src-hn").checked) sources.push("hn");
  if ($("#src-facebook").checked) sources.push("facebook");
  if ($("#src-x").checked) sources.push("x");
  if ($("#src-instagram").checked) sources.push("instagram");
  if ($("#src-youtube").checked) sources.push("youtube");
  if ($("#src-polymarket").checked) sources.push("polymarket");
  if ($("#src-github").checked) sources.push("github");
  if ($("#src-bluesky").checked) sources.push("bluesky");

  if (sources.includes("facebook")) {
    const ok = await ensureFreshCookies();
    if (!ok) return;
  }

  $("#go").disabled = true;
  clearNode($("#clusters"));
  if (cy) { cy.destroy(); cy = null; }
  { const h = $("#graphHint"); if (h) h.classList.remove("hidden"); }
  if (sentChart) { sentChart.destroy(); sentChart = null; }
  log("Starting run for \"" + topic + "\" on [" + sources.join(", ") + "]...");
  const opinion = ($("#opinion").value || "").trim() || null;
  const body = { topic, sources, opinion };
  const byok = readByok();
  if (byok && byok.provider && byok.api_key) body.byok = byok;
  const r = await fetch("/api/agent/run", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const j = await r.json();
  if (j.error || !j.run_id) {
    log("Failed: " + (j.error || "no run_id"), "err");
    $("#go").disabled = false;
    return;
  }
  runId = j.run_id;
  try { localStorage.setItem("pt:lastRunId", runId); } catch (e) {}
  $("#briefing-link").style.display = "none";
  $("#briefing-link").href = "#";
  if (window.__orch) window.__orch.begin();
  plReset();
  plActivate("seed");
  plStatus("Run starting…");
  PL2.start();
  if (sources.includes("facebook")) {
    $("#nav-shots").style.display = "inline-block";
  }
  subscribe(runId);
}

async function downloadBriefing(e) {
  if (e) { e.preventDefault(); e.stopPropagation(); }
  const link = $("#briefing-link");
  const href = link.getAttribute("href");
  if (!href || href === "#") return;
  const kind = link.getAttribute("data-kind") || "pdf";
  if (kind === "html") { window.open(href, "_blank", "noopener"); return; }
  const orig = link.textContent;
  link.textContent = "⏳ preparing…";
  try {
    const r = await fetch(href, { credentials: "same-origin" });
    if (!r.ok) {
      link.textContent = "⚠ " + r.status;
      setTimeout(() => link.textContent = orig, 2500);
      return;
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const cd = r.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename="?([^"]+)"?/i);
    a.download = m ? m[1] : ((runId || "run") + ".pdf");
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  } catch (err) {
    link.textContent = "⚠ failed";
    setTimeout(() => link.textContent = orig, 2500);
    return;
  }
  link.textContent = orig;
}

async function revealBriefingIfReady(rid) {
  if (!rid) return;
  try {
    const r = await fetch("/run/" + encodeURIComponent(rid) + "/briefing/manifest");
    if (!r.ok) return;
    const m = await r.json();
    const link = $("#briefing-link");
    link.href = "/run/" + encodeURIComponent(rid) + (m.pdf ? "/briefing/pdf" : "/briefing/html");
    link.setAttribute("data-kind", m.pdf ? "pdf" : "html");
    link.textContent = m.pdf ? "📄 Download briefing PDF" : "📄 View briefing HTML";
    link.style.display = "inline-flex";
  } catch (e) {}
}

function subscribe(rid) {
  const es = new EventSource("/events?run_id=" + encodeURIComponent(rid));
  es.onmessage = (e) => {
    let ev; try { ev = JSON.parse(e.data); } catch { return; }
    handle(ev);
    if (window.__orch) window.__orch.handle(ev);
    if (ev.type === "done") {
      // run_agent finished the analysis pipeline; the orchestration graph then
      // scores/alerts before _close, so keep the stream open until then.
      drawGraph(rid);
    }
    if (ev.type === "_close") {
      es.close();
      $("#go").disabled = false;
    }
  };
  es.onerror = () => {
    plStatus("SSE disconnected · server log still recording");
    es.close();
    $("#go").disabled = false;
  };
}

let replayTimer = null, replayFinalPosts = 0;

async function applyReplayFrame(rid, iterN) {
  try {
    const r = await fetch("/replay?run_id=" + encodeURIComponent(rid)
      + "&iter=" + encodeURIComponent(iterN));
    const j = await r.json();
    const maxN = j.max_iter || 1;
    const nq = (j.queries || []).length;
    $("#m-posts").textContent = j.n_posts;
    $("#replay-caption").textContent =
      "iteration " + j.iter + " of " + maxN + " · " + nq + " queries";
  } catch (e) {
    $("#replay-caption").textContent = "replay unavailable";
  }
}

async function setupReplay(rid) {
  let maxN = 1;
  try {
    const r = await fetch("/replay?run_id=" + encodeURIComponent(rid) + "&iter=1");
    const j = await r.json();
    maxN = j.max_iter || 1;
  } catch (e) { return; }

  const wrap = $("#replay-wrap"), slider = $("#replay-slider");
  slider.max = String(maxN);
  slider.value = String(maxN);
  replayFinalPosts = parseInt($("#m-posts").textContent, 10) || 0;
  wrap.style.display = "block";
  $("#replay-caption").textContent =
    "iteration " + maxN + " of " + maxN + " (final)";

  slider.oninput = () => {
    const v = parseInt(slider.value, 10) || 1;
    if (v >= maxN) $("#m-posts").textContent = replayFinalPosts;
    clearTimeout(replayTimer);
    replayTimer = setTimeout(() => applyReplayFrame(rid, v), 180);
  };
}

function handle(ev) {
  PL2.event(ev);
  switch (ev.type) {
    case "started":
      plReset();
      plActivate("seed");
      plStatus("Run started");
      break;
    case "seeded":
      plMeta("seed", (ev.queries || []).length + " queries");
      plActivate("fetch");
      plStatus("Fetching posts");
      break;
    case "iter_start":
      plActivate("fetch");
      plMeta("fetch", "iter " + ev.iter + " · " + (ev.queries || []).length + " queries");
      break;
    case "posts_fetched":
      $("#m-posts").textContent = ev.n_total;
      plActivate("fetch");
      plMeta("fetch", "+" + ev.n_new + " · total " + ev.n_total);
      break;
    case "low_recall":
      plMeta("fetch", "low recall (" + ev.n + ") · retry");
      break;
    case "clustered":
      $("#m-clusters").textContent = ev.k;
      $("#m-entropy").textContent = Number(ev.entropy).toFixed(2);
      plMark("fetch", "done");
      plActivate("cluster");
      plMeta("cluster", "k=" + ev.k + " · H=" + Number(ev.entropy).toFixed(2));
      break;
    case "labeled":
      renderClusters(ev.clusters || []);
      renderSentChart(ev.clusters || []);
      plMark("cluster", "done");
      plActivate("label");
      plMeta("label", (ev.clusters || []).length + " clusters named");
      break;
    case "reranked":
      // Stance is computed after the loop, so the `labeled` event always
      // carries neutral placeholders. Re-render the summary here, once the
      // real per-cluster sentiment exists, so it matches the drill-down view.
      if (ev.clusters && ev.clusters.length) {
        renderClusters(ev.clusters);
        renderSentChart(ev.clusters);
      }
      break;
    case "briefing_ready": {
      const link = $("#briefing-link");
      const href = ev.pdf || ev.html;
      if (href) {
        link.href = href;
        link.setAttribute("data-kind", ev.pdf ? "pdf" : "html");
        link.textContent = ev.pdf ? "📄 Download briefing PDF" : "📄 View briefing HTML";
        link.style.display = "inline-flex";
      }
      plMark("label", "done");
      plMark("brief", "done");
      plMeta("brief", ev.pdf ? "PDF ready" : "HTML ready");
      plStatus("Briefing ready");
      break;
    }
    case "evidence_ready":
      fetch(ev.url).then(r => r.json()).then(renderEvidence).catch(() => {});
      break;
    case "briefing_error":
      plMark("brief", "err");
      plMeta("brief", "PDF only");
      plStatus("Insights ready · PDF export failed");
      break;
    case "embed_error":
      plMark("cluster", "err");
      plMeta("cluster", "embed error");
      plStatus("Embedding failed");
      break;
    case "error":
      plStatus("Error: " + (ev.err || ""));
      break;
    case "done":
      plMark("label", "done");
      plStatus("Run complete · " + (ev.n_posts || 0) + " posts");
      $("#nav-shots").style.display = "inline-flex";
      break;
  }
}

$("#go").addEventListener("click", start);
$("#topic").addEventListener("keydown", e => { if (e.key === "Enter") start(); });
