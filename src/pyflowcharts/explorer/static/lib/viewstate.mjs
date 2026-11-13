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
