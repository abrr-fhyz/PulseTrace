/* facebook cookie-refresh modal flow */
const fbModal = $("#fb-cookie-modal");
const fbPill = $("#fb-stale-pill");
const fbSub = $("#fb-modal-sub");
const fbLog = $("#fb-modal-log");
const fbActions = $("#fb-modal-actions");
let fbJobId = null;
let fbEventSrc = null;
let fbResolve = null;

function fmtAge(s) {
  if (s == null) return "never";
  if (s < 60) return s + "s";
  if (s < 3600) return Math.floor(s / 60) + "m";
  return Math.floor(s / 3600) + "h" + Math.floor((s % 3600) / 60) + "m";
}

function openModal() { fbModal.classList.add("show"); }
function closeModal() {
  fbModal.classList.remove("show");
  if (fbEventSrc) { fbEventSrc.close(); fbEventSrc = null; }
  clearNode(fbLog);
  fbLog.style.display = "none";
}

function setActions(items) {
  clearNode(fbActions);
  for (const it of items) {
    const b = document.createElement("button");
    b.textContent = it.label;
    if (it.primary) b.className = "cta-primary";
    else b.className = "secondary";
    b.addEventListener("click", it.onClick);
    fbActions.appendChild(b);
  }
}

function fbLogLine(text, cls) {
  fbLog.style.display = "block";
  const line = elem("div", { class: "log-line " + (cls || "ev") },
                    "[" + new Date().toLocaleTimeString() + "] " + text);
  fbLog.appendChild(line);
  fbLog.scrollTop = fbLog.scrollHeight;
}

async function ensureFreshCookies() {
  let st;
  try {
    const r = await fetch("/fb/cookies/status");
    st = await r.json();
  } catch (e) {
    return true;
  }
  if (st.exists && !st.stale) return true;
  return new Promise((resolve) => {
    fbResolve = resolve;
    fbPill.className = "stale-warn";
    if (!st.exists) {
      fbPill.textContent = "⚠ no cookies on disk";
      fbSub.textContent = ("Facebook source needs info/cookies.json. Refresh "
        + "via the embedded login (a Chromium window opens — log in, then "
        + "click 'I'm logged in') or run the script in your terminal.");
    } else {
      fbPill.textContent = "⚠ cookies " + fmtAge(st.age_seconds) + " old "
                          + "(ttl " + fmtAge(st.ttl_seconds) + ")";
      fbSub.textContent = ("Cookies look stale. FB usually starts redirecting "
        + "scrapers to login after 4–8h. Refresh now or run the script "
        + "yourself.");
    }
    setActions([
      { label: "Refresh now (auto)", primary: true, onClick: doRefresh },
      { label: "Run manually", onClick: showManual },
      { label: "Skip (use as-is)", onClick: () => { closeModal(); resolve(true); } },
      { label: "Cancel run", onClick: () => { closeModal(); resolve(false); } },
    ]);
    openModal();
  });
}

function showManual() {
  clearNode(fbLog);
  fbLog.style.display = "block";
  fbLog.appendChild(elem("div", { class: "log-line ev" }, "Run this in a terminal:"));
  fbLog.appendChild(elem("div", { class: "log-line ev" }, "  .venv/bin/python scripts/fb_login.py"));
  fbLog.appendChild(elem("div", { class: "log-line ev" }, "Log in inside the Chromium window."));
  fbLog.appendChild(elem("div", { class: "log-line ev" }, "Press Enter in the terminal to save cookies."));
  setActions([
    { label: "I've done it — continue", primary: true,
      onClick: () => { closeModal(); fbResolve && fbResolve(true); } },
    { label: "Cancel", onClick: () => { closeModal(); fbResolve && fbResolve(false); } },
  ]);
}

async function doRefresh() {
  clearNode(fbLog);
  fbLog.style.display = "block";
  fbLogLine("Starting fb_login.py — a Chromium window will open shortly...");
  setActions([{ label: "Cancel", onClick: doCancel }]);
  let r;
  try {
    r = await fetch("/fb/cookies/refresh/start", { method: "POST" });
  } catch (e) {
    fbLogLine("Failed to start: " + e.message, "err");
    return;
  }
  const j = await r.json();
  if (!j.ok) { fbLogLine("Server error: " + (j.error || "unknown"), "err"); return; }
  fbJobId = j.job_id;
  fbEventSrc = new EventSource("/fb/cookies/refresh/events?job_id=" + encodeURIComponent(fbJobId));
  fbEventSrc.onmessage = (ev) => {
    let m; try { m = JSON.parse(ev.data); } catch { return; }
    if (m.type === "log") fbLogLine(m.line);
    if (m.type === "awaiting_enter") {
      fbLogLine("→ Log in in the Chromium window, then click 'I'm logged in'.", "ev");
      setActions([
        { label: "I'm logged in — save cookies", primary: true, onClick: doConfirm },
        { label: "Cancel", onClick: doCancel },
      ]);
    }
    if (m.type === "done") {
      const c = m.cookies || {};
      if (m.exit_code === 0) {
        fbLogLine("✓ Cookies saved — age " + fmtAge(c.age_seconds), "ev");
        setActions([
          { label: "Continue run", primary: true,
            onClick: () => { closeModal(); fbResolve && fbResolve(true); } },
        ]);
      } else {
        fbLogLine("✗ Login script exited " + m.exit_code, "err");
        setActions([
          { label: "Try again", primary: true, onClick: doRefresh },
          { label: "Cancel run", onClick: () => { closeModal(); fbResolve && fbResolve(false); } },
        ]);
      }
    }
    if (m.type === "cancelled") {
      fbLogLine("Cancelled.", "err");
      setActions([
        { label: "Close", onClick: () => { closeModal(); fbResolve && fbResolve(false); } },
      ]);
    }
  };
  fbEventSrc.onerror = () => { fbLogLine("SSE disconnected.", "err"); };
}

async function doConfirm() {
  if (!fbJobId) return;
  fbLogLine("Sending Enter to script...");
  try {
    const r = await fetch("/fb/cookies/refresh/confirm", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ job_id: fbJobId }),
    });
    const j = await r.json();
    if (!j.ok) fbLogLine("Confirm failed: " + (j.error || "unknown"), "err");
  } catch (e) { fbLogLine("Confirm failed: " + e.message, "err"); }
}

async function doCancel() {
  if (!fbJobId) { closeModal(); fbResolve && fbResolve(false); return; }
  try {
    await fetch("/fb/cookies/refresh/cancel", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ job_id: fbJobId }),
    });
  } catch (_) {}
}
