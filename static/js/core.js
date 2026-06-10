/* core — global DOM helpers ($, clearNode, elem). Must load before all other scripts. */
const $ = (s) => document.querySelector(s);

function clearNode(el) { while (el && el.firstChild) el.removeChild(el.firstChild); }

function elem(tag, attrs, ...children) {
  const e = document.createElement(tag);
  if (attrs) for (const k in attrs) {
    if (k === "class") e.className = attrs[k];
    else if (k === "style") e.style.cssText = attrs[k];
    else e.setAttribute(k, attrs[k]);
  }
  for (const c of children) {
    if (c == null) continue;
    e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return e;
}
