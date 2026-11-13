import { distinctTargets, resolveTarget } from "../lib/callindex.mjs";
import { formatHash } from "../lib/routing.mjs";
import { el, link } from "./dom.mjs";

export const chartHref = (key, qualname) => formatHash({ view: "chart", key, qualname });

const SEPARATOR = " › ";

export function renderCrumbs(root, route, entry) {
  const parts = [link("Call graph", formatHash({ view: "callgraph" }))];
  if (route.view === "chart") {
    parts.push(el("span", { text: SEPARATOR }), el("span", { text: route.key }));
    parts.push(el("span", { text: SEPARATOR }), el("strong", { text: route.qualname }));
  } else if (route.view === "file") {
    const label = entry ? entry.key : route.key;
    parts.push(el("span", { text: SEPARATOR }), el("strong", { text: label }));
  }
  root.replaceChildren(...parts);
}

function refLinks(label, refs) {
  const seen = new Set();
  const items = [];
  for (const ref of refs) {
    if (seen.has(ref.label)) continue;
    seen.add(ref.label);
    items.push(link(ref.label, chartHref(ref.key, ref.qualname)));
  }
  if (items.length === 0) return [];
  return [el("span", { class: "refs" }, el("span", { class: "muted", text: `${label}: ` }),
    ...items.flatMap((a, i) => (i ? [document.createTextNode(", "), a] : [a])))];
}

export function renderCalls(root, index, entry, qualname) {
  root.replaceChildren(
    ...(entry
      ? [...refLinks("Called by", index.callers(entry.doc, qualname)),
         ...refLinks("Calls", index.callees(entry.doc, qualname))]
      : []),
  );
}

// The strip under the top bar: the selected node's location and every call written in it.
export function renderDetails(root, { state, node, calls }) {
  if (!node) return root.replaceChildren();
  const parts = [];
  if (node.location) {
    const { line, end_line: end } = node.location;
    parts.push(el("span", { class: "muted", text: line === end ? `line ${line}` : `lines ${line}–${end}` }));
  }
  const targets = distinctTargets(calls, node.id);
  for (const target of targets) {
    const resolved = resolveTarget(state, target);
    const text = target.module ? `${target.module}.${target.qualname}` : target.qualname;
    parts.push(resolved ? link(`→ ${text}`, chartHref(resolved.key, resolved.qualname)) : el("span", { text: `→ ${text}` }));
  }
  for (const call of calls) {
    if (call.node === node.id && !call.target) parts.push(el("span", { class: "muted", text: call.text }));
  }
  root.replaceChildren(...parts);
}
