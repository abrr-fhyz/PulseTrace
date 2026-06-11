/* pipeline stage indicators */
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
