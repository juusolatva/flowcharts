import { nodeIdFromTitle } from "../lib/svgids.mjs";
import { el } from "./dom.mjs";
import { attachPanZoom } from "./panzoom.mjs";

export function showNotice(stage, text, links = []) {
  stage.replaceChildren(el("div", { class: "notice" }, el("p", { text }), ...links));
}

function parseSvg(text) {
  const doc = new DOMParser().parseFromString(text, "image/svg+xml");
  if (doc.querySelector("parsererror")) throw new Error("The server sent an unreadable SVG.");
  const svg = document.importNode(doc.documentElement, true);
  svg.removeAttribute("width");
  svg.removeAttribute("height");
  return svg;
}

// Puts a Graphviz SVG into the stage. Nodes are the "g.node > title" groups; the page only adds
// CSS classes (has-call, selected). Handlers receive the node ID (null for the background).
export function mountSvg(stage, text, { onClick, onDblClick, hasCall = () => false }) {
  const svg = parseSvg(text);
  const nodes = new Map();
  for (const title of svg.querySelectorAll("g.node > title")) {
    const id = nodeIdFromTitle(title.textContent);
    const group = title.parentNode;
    nodes.set(id, group);
    if (hasCall(id)) group.classList.add("has-call");
  }
  stage.replaceChildren(svg);
  const idAt = (event) => {
    const group = event.target.closest?.("g.node");
    return group ? nodeIdFromTitle(group.querySelector(":scope > title").textContent) : null;
  };
  svg.addEventListener("click", (event) => onClick?.(idAt(event)));
  svg.addEventListener("dblclick", (event) => {
    const id = idAt(event);
    if (id !== null) onDblClick?.(id);
  });
  const panzoom = attachPanZoom(stage, svg);
  let selected = null;
  return {
    ...panzoom,
    has: (id) => nodes.has(id),
    select(id) {
      selected?.classList.remove("selected");
      selected = id === null ? null : (nodes.get(id) ?? null);
      selected?.classList.add("selected");
    },
  };
}
