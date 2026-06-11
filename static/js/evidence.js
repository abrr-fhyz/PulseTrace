/* opinion evidence panel + pro/con & confidence charts */
function evList(title, arr) {
  if (!arr || !arr.length) return null;
  const ul = elem("ul", { class: "ev-list" });
  for (const item of arr) ul.appendChild(elem("li", null, String(item)));
  return elem("div", { class: "ev-sec" }, title ? elem("strong", null, title) : null, ul);
}

function evIntro(text) {
  return elem("p", { class: "ev-intro" }, text);
}

function strengthWords(strength) {
  if (strength === "strong") return "Lots of posts back this up";
  if (strength === "moderate") return "A fair few posts mention this";
  return "Only a little to go on so far";
}
function confidenceWords(pct) {
  if (pct >= 70) return "We're fairly sure";
  if (pct >= 40) return "Could go either way";
  return "Hard to say for sure";
}

function claimCard(c) {
  c = c || {};
  const strength = String(c.evidence_strength || "weak").toLowerCase();
  const conf = Math.max(0, Math.min(1, Number(c.confidence) || 0));
  const pct = Math.round(conf * 100);
  const fillColor = strength === "strong" ? "var(--pos)"
                  : strength === "moderate" ? "#fbbf24" : "var(--neu)";
  const card = elem("div", { class: "claim" },
    elem("h4", null, String(c.text || "")),
    elem("span", { class: "badge " + strength },
      confidenceWords(pct) + " · " + strengthWords(strength)),
    elem("div", { class: "conf-bar" },
      elem("div", { class: "conf-fill", style: "width:" + pct + "%;background:" + fillColor })),
  );
  if (c.reasoning) card.appendChild(elem("p", { class: "reasoning" }, String(c.reasoning)));
  const cats = c.source_categories || [];
  if (cats.length) {
    const wrap = elem("div", { class: "cats" });
    for (const cat of cats) wrap.appendChild(elem("span", { class: "chip" }, String(cat)));
    card.appendChild(wrap);
  }
  return card;
}

function reliabilityNote() {
  const n = parseInt(($("#m-posts") || {}).textContent || "0", 10) || 0;
  if (n >= 100) return { dot: "🟢", lvl: "Pretty reliable",
    why: "We found a good number of posts, so this gives a solid sense of the conversation." };
  if (n >= 30) return { dot: "🟡", lvl: "Take with a grain of salt",
    why: "We only found a handful of posts, so the full picture might be different." };
  return { dot: "🔴", lvl: "Hard to verify",
    why: "We found very few posts, so treat all of this as a rough first impression." };
}

function renderEvidence(ev) {
  if (!ev) return;
  _evidence = ev;
  $("#evidence").style.display = "";
  $("#evidence").classList.add("reveal");
  const noOp = !ev.opinion;
  $("#evidence").classList.toggle("no-opinion", noOp);
  if (noOp) {
    const active = $("#ev-tabs .ev-tab.active");
    if (active && (active.dataset.tab === "screenA" || active.dataset.tab === "screenB")) {
      document.querySelectorAll("#ev-tabs .ev-tab").forEach(t =>
        t.classList.toggle("active", t.dataset.tab === "summary"));
      document.querySelectorAll("#evidence .ev-panel").forEach(p =>
        p.hidden = p.dataset.panel !== "summary");
    }
  }

  const sum = $("#evidence .ev-panel[data-panel=summary]"); clearNode(sum);
  const es = ev.exec_summary || {};
  sum.appendChild(evIntro("The quick rundown — what people are saying, in a sentence or two."));
  if (es.plain_topic) sum.appendChild(elem("p", null, String(es.plain_topic)));
  const f1 = evList("What stood out", es.key_findings); if (f1) sum.appendChild(f1);
  const f2 = evList("What people agree on", es.agreements); if (f2) sum.appendChild(f2);
  const f3 = evList("Where people clash", es.disagreements); if (f3) sum.appendChild(f3);
  if (es.conclusion) sum.appendChild(elem("p", null, String(es.conclusion)));

  const ov = $("#evidence .ev-panel[data-panel=overview]"); clearNode(ov);
  ov.appendChild(evIntro("The main things people keep bringing up about this topic."));
  ov.appendChild(elem("p", null, ev.topic_overview ? String(ev.topic_overview)
    : "We didn't gather enough to break this down yet."));
  if (noOp && (ev.claims || []).length) {
    ov.appendChild(elem("div", { class: "ev-sec" }, elem("strong", null, "The main talking points")));
    for (const c of ev.claims) ov.appendChild(claimCard(c));
  }

  const cons = $("#evidence .ev-panel[data-panel=consensus]"); clearNode(cons);
  cons.appendChild(evIntro("Are people mostly on the same page, or split? Here's the gist."));
  const cc = ev.community_consensus || {};
  const s1 = evList("What people like", cc.top_praise); if (s1) cons.appendChild(s1);
  const s2 = evList("What people don't like", cc.top_criticism); if (s2) cons.appendChild(s2);
  const s3 = evList("Common misunderstandings", cc.misconceptions); if (s3) cons.appendChild(s3);
  const s4 = evList("What's still unclear", cc.uncertainties); if (s4) cons.appendChild(s4);
  if (cons.childNodes.length <= 1) cons.appendChild(elem("p", null, "Not enough posts to tell yet."));

  const sa = $("#evidence .ev-panel[data-panel=screenA]"); clearNode(sa);
  sa.appendChild(evIntro("Real arguments people are making in favour of this."));
  for (const c of (ev.screen_a || [])) sa.appendChild(claimCard(c));
  if (sa.childNodes.length <= 1) sa.appendChild(elem("p", null, "Nobody made a clear case for this in what we found."));

  const sb = $("#evidence .ev-panel[data-panel=screenB]"); clearNode(sb);
  sb.appendChild(evIntro("Real arguments people are making against this."));
  for (const c of (ev.screen_b || [])) sb.appendChild(claimCard(c));
  if (sb.childNodes.length <= 1) sb.appendChild(elem("p", null, "Nobody pushed back clearly in what we found."));

  const unc = $("#evidence .ev-panel[data-panel=uncertainty]"); clearNode(unc);
  const rel = reliabilityNote();
  unc.appendChild(elem("p", { class: "rel-line" },
    elem("span", { class: "rel-dot" }, rel.dot + " " + rel.lvl), " — " + rel.why));
  const ul = evList("What we're not sure about", ev.uncertainty);
  if (ul) unc.appendChild(ul);
  unc.appendChild(elem("p", { class: "ev-note" },
    "This is based on what people are posting online — not an official study."));

  const ass = $("#evidence .ev-panel[data-panel=assessment]"); clearNode(ass);
  ass.appendChild(evIntro("Putting it all together — here's how we'd sum it up."));
  ass.appendChild(elem("p", null, ev.final_assessment ? String(ev.final_assessment)
    : "We didn't gather enough to give a confident take."));
  ass.appendChild(elem("p", { class: "ev-note" },
    "Remember — this reflects online conversation, not scientific consensus."));

  drawEvidenceCharts();
  loadVoices();
}

function drawEvidenceCharts() {
  if (!_evidence) return;
  const ev = _evidence;
  if (proConChart) { proConChart.destroy(); proConChart = null; }
  if (confChart) { confChart.destroy(); confChart = null; }

  const pcCtx = $("#proConChart");
  if (pcCtx) {
    let labels, data, colors;
    if (ev.opinion) {
      labels = ["Pro", "Con"];
      data = [(ev.screen_a || []).length, (ev.screen_b || []).length];
      colors = ["#6ee7b7", "#f87171"];
    } else {
      labels = ["Neutral"];
      data = [(ev.claims || []).length];
      colors = ["#94a3b8"];
    }
    proConChart = new Chart(pcCtx, {
      type: "bar",
      data: { labels, datasets: [{ label: "claims", data, backgroundColor: colors }] },
      options: {
        responsive: true,
        plugins: { legend: { labels: { color: "#e6edf7" } } },
        scales: {
          x: { ticks: { color: "#8aa0bd" }, grid: { color: "#25324a" } },
          y: { ticks: { color: "#8aa0bd" }, grid: { color: "#25324a" }, beginAtZero: true },
        },
      },
    });
  }

  const claims = ev.claims || [];
  const cfCtx = $("#confChart");
  if (cfCtx && claims.length) {
    const labels = claims.map(c => String(c.text || "").slice(0, 28));
    const vals = claims.map(c => Math.round((Math.max(0, Math.min(1, Number(c.confidence) || 0))) * 100));
    const colors = claims.map(c => {
      const s = String(c.evidence_strength || "weak").toLowerCase();
      return s === "strong" ? "#6ee7b7" : s === "moderate" ? "#fbbf24" : "#94a3b8";
    });
    confChart = new Chart(cfCtx, {
      type: "bar",
      data: { labels, datasets: [{ label: "confidence", data: vals, backgroundColor: colors }] },
      options: {
        indexAxis: "y",
        responsive: true,
        plugins: { legend: { labels: { color: "#e6edf7" } } },
        scales: {
          x: { ticks: { color: "#8aa0bd" }, grid: { color: "#25324a" }, max: 100, beginAtZero: true },
          y: { ticks: { color: "#8aa0bd" }, grid: { color: "#25324a" } },
        },
      },
    });
  }
}

$("#ev-tabs").addEventListener("click", (e) => {
  const b = e.target.closest(".ev-tab"); if (!b) return;
  document.querySelectorAll("#ev-tabs .ev-tab").forEach(t => t.classList.toggle("active", t === b));
  const name = b.dataset.tab;
  document.querySelectorAll("#evidence .ev-panel").forEach(p => { p.hidden = p.dataset.panel !== name; });
  if (name === "viz") drawEvidenceCharts();
});
