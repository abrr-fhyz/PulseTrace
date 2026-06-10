/* captures/shots view + lightbox */
async function onEnterShots() {
  const pill = $("#shots-run-pill");
  const body = $("#shots-body");
  clearNode(body);
  if (!runId) {
    pill.textContent = "no active run";
    body.appendChild(elem("div", { class: "shots-empty" },
                          "Start a run first — captures appear here once Facebook OCR has run."));
    return;
  }
  pill.textContent = "run " + runId;
  body.appendChild(elem("div", { class: "muted" }, "Loading captures..."));
  let j;
  try {
    const r = await fetch("/shots/" + encodeURIComponent(runId));
    j = await r.json();
  } catch (e) {
    clearNode(body);
    body.appendChild(elem("div", { class: "shots-empty" }, "Failed to load captures."));
    return;
  }
  clearNode(body);
  if (!j.iters || j.iters.length === 0) {
    body.appendChild(elem("div", { class: "shots-empty" },
                          "No captures saved for this run yet."));
    return;
  }
  for (const it of j.iters) {
    const block = elem("div", { class: "iter-block" });
    block.appendChild(elem("div", { class: "iter-head" },
      elem("h3", null, it.iter.replace("_", " ")),
      elem("span", { class: "pill" }, it.count + " shots"),
    ));
    const grid = elem("div", { class: "shots-grid" });
    const sample = it.shots.slice(0, 5);
    for (const fn of sample) {
      const src = "/shots/" + encodeURIComponent(runId)
                + "/" + encodeURIComponent(it.iter)
                + "/" + encodeURIComponent(fn);
      const card = elem("div", { class: "shot-card" });
      const img = elem("img", { src: src, alt: fn, loading: "lazy" });
      card.appendChild(img);
      card.appendChild(elem("div", { class: "meta" },
        elem("span", null, fn.replace(/_\d+\.png$/, "")),
        elem("span", null, "open ↗"),
      ));
      card.addEventListener("click", () => openLightbox(src));
      grid.appendChild(card);
    }
    if (it.shots.length > sample.length) {
      grid.appendChild(elem("div", { class: "muted",
                                      style: "align-self:center;padding:0 8px;font-size:12px" },
                            "+" + (it.shots.length - sample.length) + " more"));
    }
    block.appendChild(grid);
    body.appendChild(block);
  }
}

function openLightbox(src) {
  const img = $("#lightbox-img");
  img.src = src;
  $("#lightbox").classList.add("show");
}
function closeLightbox(ev) {
  if (ev && ev.target && ev.target.tagName === "IMG"
      && ev.target.id === "lightbox-img") return;
  $("#lightbox").classList.remove("show");
}
