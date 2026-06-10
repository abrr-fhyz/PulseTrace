/* view router (#/landing|byok|app|shots) + chat link */
const VIEWS = ["landing", "byok", "app", "shots"];
function goto(name) {
  if (!VIEWS.includes(name)) name = "landing";
  // Protected views require a signed-in user when auth is active.
  if (window.__AUTH__ && !(window.__USER__ || "").trim()
      && (name === "app" || name === "byok" || name === "shots")) {
    location.href = "/login"; return;
  }
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
  
  // If auth is active and user is logged in, default to app; otherwise landing
  const user = (window.__USER__ || "").trim();
  const defaultView = (window.__AUTH__ && user) ? "app" : "landing";
  
  const cur = VIEWS.find(v => $("#view-" + v).classList.contains("active"));
  goto(cur || defaultView);
}
window.addEventListener("hashchange", routeFromHash);

// Landing "Launch Platform": gate through auth → app when auth is active.
// In single-user local mode (auth off) jump straight to app as before.
function launchPlatform() {
  const user = (window.__USER__ || "").trim();
  if (window.__AUTH__ && !user) { location.href = "/login"; return; }
  goto("app");
}

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
