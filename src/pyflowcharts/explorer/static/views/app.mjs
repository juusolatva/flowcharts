import { buildCallIndex, distinctTargets, resolveTarget } from "../lib/callindex.mjs";
import { createApi, isIgnorable } from "../lib/client.mjs";
import { opensSearch } from "../lib/keys.mjs";
import { formatHash, parseHash } from "../lib/routing.mjs";
import { fallbackFunction, nodeForLine } from "../lib/sourcemap.mjs";
import { splitCallgraphId } from "../lib/svgids.mjs";
import { chartState } from "../lib/viewstate.mjs";
import { mountSvg, showNotice } from "./chart.mjs";
import { link } from "./dom.mjs";
import { startLive } from "./live.mjs";
import { createSidebar } from "./sidebar.mjs";
import { createSource } from "./source.mjs";
import { chartHref, renderCalls, renderCrumbs, renderDetails } from "./topbar.mjs";

const EMPTY = "No charts yet — add Python files to the explored paths.";
const MODULE = "<module>";
const $ = (id) => document.getElementById(id);
const [stage, details] = [$("stage"), $("details")];

let state = null;
let index = null;
let route = parseHash(location.hash);
let current = null; // the open flowchart: { entry, chart, handle }
let handle = null; // the mounted SVG's pan/zoom/select handle, call graph included
let selected = null;
let token = 0;
let busy = false;
let live = "reconnecting";
let failed = false;

function paintStatus() {
  let value = live;
  if (busy) value = "reparsing";
  else if (failed) value = "reconnecting";
  $("status").dataset.state = value;
  $("status").title = value === "reparsing" ? "re-parsing" : value;
}

const navigate = (target) => { location.hash = formatHash(target); };

const api = createApi({
  onState(newState) {
    try {
      state = newState;
      index = buildCallIndex(newState);
      sidebar.render(newState, route);
      void show(); // show() reports its own errors
    } catch (error) {
      console.error(error);
      notice(`Could not draw the explorer: ${error.message}`);
    }
  },
  onOk() { failed = false; },
  onBusy(value) { busy = value; paintStatus(); },
  onError(error) {
    console.error(error);
    failed = true;
    paintStatus();
    if (!state) notice(`Could not load the explorer state: ${error.message}`);
  },
});

const sidebar = createSidebar({
  tree: $("tree"), search: $("search"), warnings: $("warnings"), onOpen: navigate,
});

const source = createSource({
  lines: $("source-lines"), title: $("source-title"), hint: $("source-hint"),
  toggle: $("source-toggle"), layout: $("layout"),
  onLine(line) {
    if (!current) return;
    const id = nodeForLine(current.chart, line);
    if (id) return select(id);
    const qualname = fallbackFunction(current.entry, line);
    if (qualname && qualname !== current.chart.qualname) {
      source.showHint(`go to ${qualname}`, chartHref(current.entry.key, qualname));
    } else {
      source.clearHint();
    }
  },
});

function select(id) {
  selected = id;
  current.handle.select(id);
  const node = current.chart.nodes.find((n) => n.id === id) ?? null;
  renderDetails(details, { state, node, calls: current.chart.calls });
  source.clearHint();
  if (node?.location) source.highlight(node.location.line, node.location.end_line);
  else source.unhighlight();
}

function notice(text, ...links) {
  current = null;
  handle = null;
  details.replaceChildren();
  showNotice(stage, text, links);
}

function gone() {
  source.clear("");
  notice("This chart no longer exists.", link("Call graph", "#/"),
    link("Search", "#", { onclick: (e) => { e.preventDefault(); sidebar.focusSearch(); } }));
}

async function showCallgraph(mine) {
  source.clear("Open a function to see its source.");
  if (!state.entries.some((e) => e.functions.length > 0 || e.has_module)) return notice(EMPTY);
  const text = await api.text("/api/svg/callgraph");
  if (mine !== token) return;
  details.replaceChildren();
  current = null;
  handle = mountSvg(stage, text, {
    onClick(id) {
      if (id === null) return;
      const { doc, qualname } = splitCallgraphId(id);
      const entry = state.entries.find((e) => e.doc === doc);
      if (entry) navigate({ view: "chart", key: entry.key, qualname });
    },
  });
}

function showFileNotice(entry) {
  source.clear("");
  notice(`⚠ ${entry.error ?? "No problems in this file."}`);
}

async function showChart(mine, entry) {
  const q = route.qualname;
  const view = chartState(entry, q, MODULE);
  if (view === "gone") return gone();
  if (view === "error") return showFileNotice(entry);
  const skipped = entry.skipped.find((s) => s.qualname === q);
  const sourceUrl = `/api/source/${entry.doc}`;
  if (skipped) {
    const text = await api.text(sourceUrl);
    if (mine !== token) return;
    notice(`⚠ ${skipped.message}`);
    source.show(entry.source, text);
    return source.highlight(skipped.line, skipped.line);
  }
  const [svgText, doc, text] = await Promise.all([
    api.text(`/api/svg/chart/${entry.doc}/${encodeURIComponent(q)}`),
    api.json(`/api/document/${entry.doc}`),
    api.text(sourceUrl),
  ]);
  if (mine !== token) return;
  const chart = q === MODULE ? doc.module : doc.functions.find((f) => f.qualname === q);
  if (!chart) return gone();
  const withCall = new Set(chart.calls.filter((c) => c.target).map((c) => c.node));
  handle = mountSvg(stage, svgText, {
    hasCall: (id) => withCall.has(id),
    onClick: (id) => select(id),
    onDblClick(id) {
      const targets = distinctTargets(chart.calls, id);
      const resolved = targets.length === 1 ? resolveTarget(state, targets[0]) : null;
      if (resolved) navigate({ view: "chart", ...resolved });
    },
  });
  current = { entry, chart, handle };
  source.show(entry.source, text);
  select(handle.has(selected) ? selected : null);
}

async function show() {
  const mine = ++token;
  if (!state) return;
  const entry = state.entries.find((e) => e.key === route.key);
  renderCrumbs($("crumbs"), route, entry);
  renderCalls($("calls"), index, route.view === "chart" ? entry : null, route.qualname);
  try {
    if (route.view === "callgraph") await showCallgraph(mine);
    else if (route.view === "chart") await showChart(mine, entry);
    else if (entry) showFileNotice(entry);
    else gone();
  } catch (error) {
    if (mine !== token || isIgnorable(error)) return;
    notice(`Could not load this view: ${error.message}`);
  }
}

window.addEventListener("hashchange", () => {
  route = parseHash(location.hash);
  selected = null;
  sidebar.setRoute(route);
  void show(); // show() reports its own errors
});
document.addEventListener("keydown", (event) => {
  if (!opensSearch(event)) return;
  event.preventDefault();
  sidebar.focusSearch();
});
$("fit").addEventListener("click", () => handle?.fit());
$("zoom-in").addEventListener("click", () => handle?.zoom(1.25));
$("zoom-out").addEventListener("click", () => handle?.zoom(1 / 1.25));
$("back").addEventListener("click", () => history.back());
$("forward").addEventListener("click", () => history.forward());

await api.refresh();
startLive({
  onGeneration: (generation) => api.noteGeneration(generation),
  onStatus(value) { live = value; paintStatus(); },
});
