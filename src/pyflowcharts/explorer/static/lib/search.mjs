const MODULE = "<module>";

function* charts(entry) {
  for (const f of entry.functions ?? []) yield { qualname: f.qualname, skipped: false };
  for (const s of entry.skipped ?? []) yield { qualname: s.qualname, skipped: true };
  if (entry.has_module) yield { qualname: MODULE, skipped: false };
}

export function searchCharts(entries, query) {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  const results = [];
  for (const entry of entries) {
    for (const { qualname, skipped } of charts(entry)) {
      if (qualname.toLowerCase().includes(needle) || entry.key.toLowerCase().includes(needle)) {
        results.push({ key: entry.key, qualname, label: `${qualname} — ${entry.key}`, skipped });
      }
    }
  }
  return results;
}
