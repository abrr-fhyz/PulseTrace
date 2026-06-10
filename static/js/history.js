/* past-searches history drawer (list/open/delete/restore) */
function openHistory() {
  loadHistory();
  $("#hist-drawer").classList.add("open");
  $("#hist-drawer").setAttribute("aria-hidden", "false");
  $("#hist-backdrop").classList.add("open");
}
function closeHistory() {
  $("#hist-drawer").classList.remove("open");
  $("#hist-drawer").setAttribute("aria-hidden", "true");
  $("#hist-backdrop").classList.remove("open");
}

function newRun() {
  closeHistory();
  goto("app");
  blankDashboard();
  $("#topic").focus();
}

function openRun(rid) {
  closeHistory();
  blankDashboard();
  restoreRun(rid);
  document.querySelectorAll("#history-list .hist-row").forEach(r =>
    r.classList.toggle("active", r.getAttribute("data-rid") === rid));
}

async function loadHistory() {
  const box = $("#history-list");
  if (!box) return;
  try {
    const r = await fetch("/runs?limit=50");
    const runs = await r.json();
    clearNode(box);
    if (!Array.isArray(runs) || !runs.length) {
      box.appendChild(elem("div", { class: "hist-empty" }, "No past searches yet."));
      return;
    }
    for (const run of runs) box.appendChild(historyRow(run));
  } catch (e) {}
}

function historyRow(run) {
  const active = run.run_id === runId ? " active" : "";
  const open = elem("button", { class: "hist-open", title: "Open this search" },
    elem("span", { class: "hist-topic" }, run.topic || "Untitled"),
    elem("span", { class: "hist-time" },
      relTime(run.started_at) + " · " + (run.n_posts || 0) + " posts"));
  open.addEventListener("click", () => openRun(run.run_id));
  const del = elem("button",
    { class: "hist-del", title: "Delete this search", "aria-label": "Delete search" }, "🗑");
  del.addEventListener("click", (e) => { e.stopPropagation(); deleteRun(run.run_id, run.topic); });
  return elem("div", { class: "hist-row" + active, "data-rid": run.run_id }, open, del);
}

async function deleteRun(rid, topic) {
  if (!confirm("Delete this past search?\n\n" + (topic || rid))) return;
  try { await fetch("/runs/" + encodeURIComponent(rid), { method: "DELETE" }); } catch (e) {}
  if (rid === runId) blankDashboard();
  if (localStorage.getItem("pt:lastRunId") === rid) {
    try { localStorage.removeItem("pt:lastRunId"); } catch (e) {}
  }
  loadHistory();
}

async function restoreRun(rid) {
  runId = rid;
  let info;
  try {
    const r = await fetch("/run-info?run_id=" + encodeURIComponent(rid));
    if (!r.ok) return;
    info = await r.json();
  } catch (e) { return; }
  const run = info.run || {};
  // Persisted clusters carry a `members` array; the live labeled/reranked
  // events carry a precomputed `n`. Normalise so renderClusters can sort + show.
  const clusters = (info.clusters || []).map(c => ({ ...c, n: (c.members || []).length }));
  if (!clusters.length) return;
  renderClusters(clusters);
  renderSentChart(clusters);
  const m = run.metrics || {};
  if (m.posts != null) $("#m-posts").textContent = m.posts;
  if (m.clusters != null) $("#m-clusters").textContent = m.clusters;
  if (run.topic && !$("#topic").value) $("#topic").value = run.topic;
  revealBriefingIfReady(rid);
  drawGraph(rid).catch(() => {});
  loadVoices();
  fetch("/run/" + encodeURIComponent(rid) + "/evidence")
    .then(r => (r.ok ? r.json() : null))
    .then(j => { if (j && !j.error) renderEvidence(j); })
    .catch(() => {});
  try { localStorage.setItem("pt:lastRunId", rid); } catch (e) {}
  document.querySelectorAll("#history-list .hist-row").forEach(r =>
    r.classList.toggle("active", r.getAttribute("data-rid") === rid));
}
