/* cytoscape topic graph + color helpers + orbital spin */
if (window.cytoscapeFcose) cytoscape.use(window.cytoscapeFcose);

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
function hexToRgb(h) {
  h = h.replace("#", "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
function sentimentColor(s) {
  s = s || {};
  const pos = +s.pos || 0, neu = +s.neu || 0, neg = +s.neg || 0;
  const total = pos + neu + neg || 1;
  const [cp, cu, cn] = [cssVar("--pos"), cssVar("--neu"), cssVar("--neg")].map(hexToRgb);
  const mix = [0, 1, 2].map((i) =>
    Math.round((cp[i] * pos + cu[i] * neu + cn[i] * neg) / total));
  return `rgb(${mix[0]},${mix[1]},${mix[2]})`;
}

function sizeOf(ele) { return 26 + Math.sqrt(ele.data("size") || 0) * 10; }

function lightenRgb(rgb, amt) {
  const m = /rgb\((\d+),\s*(\d+),\s*(\d+)\)/.exec(rgb || "");
  if (!m) return rgb;
  const mix = [1, 2, 3].map((i) => Math.round(+m[i] + (255 - +m[i]) * amt));
  return `rgb(${mix[0]},${mix[1]},${mix[2]})`;
}

let graphSpin = null;
function stopGraphSpin() {
  if (graphSpin) { cancelAnimationFrame(graphSpin.raf); graphSpin = null; }
}
// Subtle, continuous orbital rotation so the topic graph reads as "alive".
// Operates on model positions (cheap for a handful of nodes), pauses during
// interaction, and bails out under prefers-reduced-motion.
function startGraphSpin() {
  stopGraphSpin();
  if (!cy || cy.nodes().length < 2) return;
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const nodes = cy.nodes();
  let cx = 0, cyc = 0;
  nodes.forEach((n) => { const p = n.position(); cx += p.x; cyc += p.y; });
  cx /= nodes.length; cyc /= nodes.length;
  const base = nodes.map((n) => {
    const p = n.position(), dx = p.x - cx, dy = p.y - cyc;
    return { n, r: Math.hypot(dx, dy), theta: Math.atan2(dy, dx) };
  });
  const SPEED = 0.00005; // rad/ms -> ~one revolution per ~125s
  const state = { paused: false, raf: 0, angle: 0, last: performance.now() };
  graphSpin = state;
  function frame(now) {
    if (graphSpin !== state || !cy) return;
    const dt = now - state.last; state.last = now;
    if (!state.paused) {
      state.angle += SPEED * dt;
      const a = state.angle;
      cy.batch(() => base.forEach((b) => {
        const t = b.theta + a;
        b.n.position({ x: cx + b.r * Math.cos(t), y: cyc + b.r * Math.sin(t) });
      }));
    }
    state.raf = requestAnimationFrame(frame);
  }
  state.raf = requestAnimationFrame(frame);
}

async function drawGraph(rid) {
  const r = await fetch("/graph?run_id=" + encodeURIComponent(rid));
  const j = await r.json();
  const nodes = (j.nodes || []).map((n) => {
    const color = sentimentColor(n.data.sentiment);
    return { data: { ...n.data, _color: color, _hi: lightenRgb(color, 0.55) } };
  });
  const edges = j.edges || [];
  const hint = $("#graphHint");
  if (hint) hint.classList.toggle("hidden", nodes.length > 0);
  stopGraphSpin();
  if (cy) cy.destroy();
  if (!nodes.length) { cy = null; return; }

  const txt = cssVar("--text"), muted = cssVar("--muted"),
        accent = cssVar("--accent2"), panel = cssVar("--panel");

  cy = cytoscape({
    container: $("#graph"),
    elements: [...nodes, ...edges],
    minZoom: 0.2, maxZoom: 3, pixelRatio: "auto",
    style: [
      { selector: "node", style: {
          "label": "data(label)", "color": txt, "font-size": "12px",
          "font-weight": 600, "font-family": "Inter, sans-serif",
          "background-color": "data(_color)",
          "background-fill": "radial-gradient",
          "background-gradient-stop-colors": (ele) => ele.data("_hi") + " " + ele.data("_color"),
          "background-gradient-stop-positions": "0% 100%",
          "border-width": 2, "border-color": panel, "border-opacity": 0.9,
          "width": sizeOf, "height": sizeOf,
          "text-valign": "bottom", "text-margin-y": 6,
          "text-max-width": "120px", "text-wrap": "ellipsis",
          "text-background-color": panel, "text-background-opacity": 0.55,
          "text-background-padding": "2px", "text-background-shape": "roundrectangle",
          "overlay-opacity": 0, "transition-property": "opacity border-color border-width",
          "transition-duration": "0.18s",
      }},
      { selector: "edge", style: {
          "width": (ele) => 1.2 + (ele.data("weight") || 0) * 5,
          "line-color": muted, "opacity": (ele) => 0.15 + (ele.data("weight") || 0) * 0.45,
          "curve-style": "straight",
      }},
      { selector: "node.faded", style: { "opacity": 0.18 } },
      { selector: "edge.faded", style: { "opacity": 0.04 } },
      { selector: "node.hl", style: { "border-color": accent, "border-width": 3 } },
      { selector: "edge.hl", style: { "line-color": accent, "opacity": 0.85 } },
      { selector: "node:selected", style: { "border-color": accent, "border-width": 4 } },
    ],
    layout: {
      name: window.cytoscapeFcose ? "fcose" : "cose",
      animate: true, animationDuration: 600, padding: 40,
      nodeSeparation: 140, idealEdgeLength: 130, nodeRepulsion: 9000,
    },
  });

  cy.on("mouseover", "node", (e) => {
    const nb = e.target.closedNeighborhood();
    cy.elements().addClass("faded");
    nb.removeClass("faded").addClass("hl");
    if (graphSpin) graphSpin.paused = true;
  });
  cy.on("mouseout", "node", () => {
    cy.elements().removeClass("faded hl");
    if (graphSpin) { graphSpin.last = performance.now(); graphSpin.paused = false; }
  });
  cy.on("grab", "node", () => { if (graphSpin) graphSpin.paused = true; });
  // Dragging reseats nodes, so rebuild the orbit from their new positions.
  cy.on("free", "node", () => startGraphSpin());
  cy.on("layoutstop", () => { cy.fit(undefined, 40); startGraphSpin(); });

  $("#gZoomIn").onclick = () => cy && cy.zoom({ level: cy.zoom() * 1.3, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  $("#gZoomOut").onclick = () => cy && cy.zoom({ level: cy.zoom() / 1.3, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  $("#gFit").onclick = () => cy && cy.fit(undefined, 40);

  if (!window._graphResize) {
    window._graphResize = true;
    window.addEventListener("resize", () => { if (cy) { cy.resize(); cy.fit(undefined, 40); } });
  }
}
