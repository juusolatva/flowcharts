// Which state a chart route shows for its entry: a file error wins over everything else.
export function chartState(entry, qualname, moduleName) {
  if (!entry) return "gone";
  if (entry.error) return "error";
  if (entry.skipped.some((s) => s.qualname === qualname)) return "skipped";
  const exists =
    entry.functions.some((f) => f.qualname === qualname) ||
    (qualname === moduleName && entry.has_module);
  return exists ? "chart" : "gone";
}

// Identity of what a route draws, so a redraw can tell whether it shows the same chart:
// "callgraph", a chart key, or null for views without a chart.
export function viewKey(route) {
  if (route.view === "callgraph") return "callgraph";
  if (route.view === "chart") return JSON.stringify([route.key, route.qualname]);
  return null;
}

// The current viewBox ([x, y, width, height]) if the user moved it from the initial one, else
// null: an untouched view should fit the redrawn chart, which may have grown.
export function movedView(initial, current) {
  return current.every((value, i) => value === initial[i]) ? null : current;
}

// Remembers the moved view of the chart last shown, so a re-parse that redraws the same chart
// keeps the user's pan and zoom. Opening any other chart replaces the memory; a null key
// (nothing drawn) leaves it, so a chart that is briefly skipped comes back as it was.
export function createViewMemory() {
  let saved = null; // { key, box }
  return {
    remember(key, box) {
      if (key !== null) saved = { key, box };
    },
    recall(key) {
      return key !== null && saved?.key === key ? saved.box : null;
    },
  };
}
