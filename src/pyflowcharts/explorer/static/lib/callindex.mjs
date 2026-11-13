export function distinctTargets(calls, nodeId) {
  const seen = new Set();
  const targets = [];
  for (const call of calls) {
    if (call.node !== nodeId || !call.target) continue;
    const id = JSON.stringify([call.target.module, call.target.qualname]);
    if (seen.has(id)) continue;
    seen.add(id);
    targets.push(call.target);
  }
  return targets;
}

export function resolveTarget(state, target) {
  if (!target.module) return null;
  const matches = state.entries.filter((e) => e.module_name === target.module);
  return matches.length === 1 ? { key: matches[0].key, qualname: target.qualname } : null;
}

function qualnameCounts(entries) {
  const counts = new Map();
  for (const entry of entries) {
    const names = new Set([
      ...(entry.functions ?? []).map((f) => f.qualname),
      ...(entry.has_module ? ["<module>"] : []),
    ]);
    for (const name of names) counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return counts;
}

export function buildCallIndex(state) {
  const byDoc = new Map(state.entries.map((e) => [e.doc, e]));
  const counts = qualnameCounts(state.entries);
  const out = new Map();
  const inc = new Map();
  const slot = (map, doc, qualname) => {
    const id = JSON.stringify([doc, qualname]);
    if (!map.has(id)) map.set(id, []);
    return map.get(id);
  };
  const ref = (doc, qualname) => {
    const entry = byDoc.get(doc);
    if (!entry) return null;
    const label = (counts.get(qualname) ?? 0) > 1 ? `${qualname} (${entry.key})` : qualname;
    return { doc, key: entry.key, qualname, label };
  };
  for (const [[fromDoc, fromName], [toDoc, toName]] of state.edges ?? []) {
    const from = ref(fromDoc, fromName);
    const to = ref(toDoc, toName);
    if (!from || !to) continue;
    slot(out, fromDoc, fromName).push(to);
    slot(inc, toDoc, toName).push(from);
  }
  return {
    callers: (doc, qualname) => slot(inc, doc, qualname).slice(),
    callees: (doc, qualname) => slot(out, doc, qualname).slice(),
  };
}
