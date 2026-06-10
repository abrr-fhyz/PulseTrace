/* view router (#/landing|byok|app|shots) + chat link */
const VIEWS = ["landing", "byok", "app", "shots"];
function goto(name) {
  if (!VIEWS.includes(name)) name = "landing";
  if (location.hash !== "#/" + name) location.hash = "#/" + name;
  for (const v of VIEWS) $("#view-" + v).classList.toggle("active", v === name);
  window.scrollTo({ top: 0, behavior: "instant" });
  if (name === "app") onEnterApp();
  if (name === "byok") onEnterByok();
  if (name === "shots") onEnterShots();
}
function routeFromHash() {
  const m = (location.hash || "").match(/^#\/(landing|byok|app|shots)/);
  if (m) { goto(m[1]); return; }
  const cur = VIEWS.find(v => $("#view-" + v).classList.contains("active"));
  goto(cur || "landing");
}
window.addEventListener("hashchange", routeFromHash);

// A run reference (#/app?run=<id>) survives only the first paint: we capture it
// at load, restore that run, then strip it so a later refresh starts fresh.
function runRefFromHash() {
  const h = location.hash || "";
  const q = h.indexOf("?");
  if (q < 0) return null;
  try { return new URLSearchParams(h.slice(q + 1)).get("run"); } catch (e) { return null; }
}
let _bootRunId = runRefFromHash();

function openChat() {
  const rid = runId || (function(){ try { return localStorage.getItem("pt:lastRunId"); } catch(e){ return null; } })();
  location.href = rid ? ("/chat?run_id=" + encodeURIComponent(rid)) : "/chat";
}
