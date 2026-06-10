/* BYOK: provider list, key storage, validation, status badge */
const BYOK_LS_KEY = "pulsetrace.byok.v1";
let providers = [];

async function loadProviders() {
  if (providers.length) return providers;
  try {
    const r = await fetch("/providers");
    const j = await r.json();
    providers = j.providers || [];
  } catch (e) { providers = []; }
  return providers;
}

function readByok() {
  try { return JSON.parse(localStorage.getItem(BYOK_LS_KEY) || "null"); }
  catch { return null; }
}
function writeByok(b) {
  if (b) localStorage.setItem(BYOK_LS_KEY, JSON.stringify(b));
  else   localStorage.removeItem(BYOK_LS_KEY);
}

async function onEnterByok() {
  const sel = $("#byok-provider");
  const list = await loadProviders();
  clearNode(sel);
  for (const p of list) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.enabled ? p.label : (p.label + " — coming soon");
    if (!p.enabled) opt.disabled = true;
    sel.appendChild(opt);
  }
  const saved = readByok();
  if (saved) {
    sel.value = saved.provider || "gemini";
    $("#byok-key").value = saved.api_key || "";
  } else {
    sel.value = "gemini";
  }
  updateHint();
  refreshStatus(saved ? { ok: true, provider: saved.provider, persisted: true } : null);
}

function updateHint() {
  const sel = $("#byok-provider").value;
  const p = providers.find(x => x.id === sel);
  $("#byok-hint").textContent = p ? ("Format: " + p.key_hint) : "";
}

function refreshStatus(state) {
  const el = $("#byok-status");
  el.className = "status-pill";
  if (!state) { el.classList.add("idle"); el.textContent = "No key validated yet"; return; }
  if (state.ok) {
    el.classList.add("ok");
    el.textContent = "✓ " + state.provider + " key " + (state.persisted ? "saved" : "validated");
  } else {
    el.classList.add("err");
    el.textContent = "✗ " + (state.error || "validation failed");
  }
  updateAppBadge();
}

function updateAppBadge() {
  const b = $("#byok-badge");
  const saved = readByok();
  if (saved && saved.provider && saved.api_key) {
    b.style.display = "inline-flex";
    b.textContent = "🔑 BYOK · " + saved.provider;
  } else {
    b.style.display = "none";
  }
}

async function validateByok() {
  const provider = $("#byok-provider").value;
  const api_key  = $("#byok-key").value.trim();
  if (!api_key) { refreshStatus({ ok: false, error: "key required" }); return; }
  $("#byok-status").className = "status-pill idle";
  $("#byok-status").textContent = "Validating…";
  try {
    const r = await fetch("/byok/validate", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ provider, api_key }),
    });
    const j = await r.json();
    if (j.ok) {
      writeByok({ provider, api_key });
      refreshStatus({ ok: true, provider, persisted: true });
      updateAppBadge();
      
      // Check if there's a pending search to resume
      const pending = getPendingSearch();
      if (pending) {
        clearPendingSearch();
        setTimeout(() => {
          goto("app");
          resumePendingSearch();
        }, 700);
      } else {
        setTimeout(() => goto("app"), 700);
      }
    } else {
      refreshStatus({ ok: false, error: j.error || "invalid key" });
    }
  } catch (e) {
    refreshStatus({ ok: false, error: e.message || String(e) });
  }
}

function clearByok() {
  writeByok(null);
  $("#byok-key").value = "";
  refreshStatus(null);
  updateAppBadge();
}

document.addEventListener("change", e => {
  if (e.target && e.target.id === "byok-provider") updateHint();
});

$("#byok-validate").addEventListener("click", validateByok);
$("#byok-clear").addEventListener("click", clearByok);

/* ── Pending search handling ──────────────────────────────────────────────
   When user tries to search but has no BYOK key, save search params and
   navigate to BYOK view. After key validation, resume the search. */
const PENDING_SEARCH_LS_KEY = "pulsetrace.pending_search.v1";

function setPendingSearch(topic, sources, opinion) {
  try {
    localStorage.setItem(PENDING_SEARCH_LS_KEY, JSON.stringify({ topic, sources, opinion }));
  } catch (e) {}
}

function getPendingSearch() {
  try {
    const data = localStorage.getItem(PENDING_SEARCH_LS_KEY);
    return data ? JSON.parse(data) : null;
  } catch (e) {
    return null;
  }
}

function clearPendingSearch() {
  try {
    localStorage.removeItem(PENDING_SEARCH_LS_KEY);
  } catch (e) {}
}

async function resumePendingSearch() {
  const pending = getPendingSearch();
  if (!pending) return;
  clearPendingSearch();
  
  // Restore search fields
  $("#topic").value = pending.topic || "";
  $("#opinion").value = pending.opinion || "";
  
  // Restore source checkboxes
  const sources = pending.sources || [];
  document.querySelectorAll('input[id^="src-"]').forEach(cb => {
    cb.checked = sources.includes(cb.id.replace("src-", ""));
  });
  
  // Small delay to ensure DOM is ready, then trigger search
  setTimeout(() => start(), 100);
}
