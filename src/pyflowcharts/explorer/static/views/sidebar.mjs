import { searchCharts } from "../lib/search.mjs";
import { buildTree } from "../lib/tree.mjs";
import { formatHash } from "../lib/routing.mjs";
import { el, link } from "./dom.mjs";
import { chartHref } from "./topbar.mjs";

const MODULE = "<module>";

export function createSidebar({ tree, search, warnings, onOpen }) {
  let state = null;
  let route = { view: "callgraph" };
  let matches = [];
  let active = 0;
  let warningsOpen = false;
  const closed = new Set();

  const isCurrent = (key, qualname) =>
    route.view === "chart" && route.key === key && route.qualname === qualname;

  function chartItem(entry, qualname, skipped) {
    const warning = entry.skipped.find((s) => s.qualname === qualname);
    const a = link(skipped ? `⚠ ${qualname}` : qualname, chartHref(entry.key, qualname));
    if (skipped) a.title = warning?.message ?? "";
    a.className = [skipped ? "skipped" : "", isCurrent(entry.key, qualname) ? "active" : ""].join(" ").trim();
    return el("li", {}, a);
  }

  function fileItem({ label, entry }) {
    const charts = [
      ...entry.functions.map((f) => ({ qualname: f.qualname, line: f.line, skipped: false })),
      ...entry.skipped.map((s) => ({ qualname: s.qualname, line: s.line, skipped: true })),
    ].sort((a, b) => a.line - b.line);
    if (entry.has_module) charts.push({ qualname: MODULE, skipped: false });
    let head;
    if (entry.error) {
      head = link(`⚠ ${label}`, formatHash({ view: "file", key: entry.key }), { title: entry.error, class: "file-error" });
      if (route.view === "file" && route.key === entry.key) head.classList.add("active");
    } else {
      head = el("span", { class: entry.empty ? "file empty" : "file", text: label });
    }
    return el("li", {}, head, el("ul", {}, ...charts.map((c) => chartItem(entry, c.qualname, c.skipped))));
  }

  function folderItem(folder) {
    const details = el("details", {}, el("summary", { text: folder.name }), folderList(folder));
    details.open = !closed.has(folder.path);
    details.addEventListener("toggle", () => {
      if (details.open) closed.delete(folder.path);
      else closed.add(folder.path);
    });
    return el("li", {}, details);
  }

  const folderList = (folder) =>
    el("ul", {}, ...folder.folders.map(folderItem), ...folder.files.map(fileItem));

  function drawMatches() {
    active = Math.min(active, Math.max(matches.length - 1, 0));
    const items = matches.map((m, i) => {
      const a = link(m.skipped ? `⚠ ${m.label}` : m.label, chartHref(m.key, m.qualname));
      if (i === active) a.className = "active";
      return el("li", {}, a);
    });
    tree.replaceChildren(items.length ? el("ul", { class: "matches" }, ...items) : el("p", { class: "muted", text: "No matches." }));
  }

  function drawWarnings() {
    const skipped = state.entries.flatMap((e) => e.skipped.map((s) => `${e.key}: ${s.qualname}: ${s.message}`));
    const errors = state.entries.filter((e) => e.error).map((e) => `${e.key}: ${e.error}`);
    const count = state.messages.length + skipped.length;
    const toggle = el("button", {
      type: "button",
      text: `⚠ ${count} warning${count === 1 ? "" : "s"}`,
      onclick: () => { warningsOpen = !warningsOpen; drawWarnings(); },
    });
    const lines = warningsOpen ? [...state.messages, ...skipped, ...errors] : [];
    warnings.replaceChildren(toggle, ...(count + errors.length === 0 && warningsOpen ? [el("p", { class: "muted", text: "None." })] : []),
      ...lines.map((text) => el("p", { text })));
  }

  function draw() {
    if (!state) return;
    matches = searchCharts(state.entries, search.value);
    if (search.value.trim()) drawMatches();
    else tree.replaceChildren(folderList(buildTree(state.entries)));
    drawWarnings();
  }

  function open(match) {
    search.value = "";
    onOpen({ view: "chart", key: match.key, qualname: match.qualname });
  }

  search.addEventListener("input", () => { active = 0; draw(); });
  search.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      active = Math.max(0, Math.min(matches.length - 1, active + (event.key === "ArrowDown" ? 1 : -1)));
      drawMatches();
    } else if (event.key === "Enter" && matches[active]) {
      open(matches[active]);
    } else if (event.key === "Escape") {
      search.value = "";
      draw();
    }
  });

  return {
    render(newState, newRoute) { state = newState; route = newRoute; draw(); },
    setRoute(newRoute) { route = newRoute; draw(); },
    focusSearch() { search.focus(); },
  };
}
