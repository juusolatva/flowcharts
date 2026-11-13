function smallest(items, line, span, pick) {
  let best = null;
  let bestSpan = Infinity;
  for (const item of items) {
    const [start, end] = span(item);
    if (line < start || line > end || end - start >= bestSpan) continue;
    best = pick(item);
    bestSpan = end - start;
  }
  return best;
}

export function nodeForLine(chart, line) {
  const located = chart.nodes.filter((n) => n.location !== null);
  return smallest(located, line, (n) => [n.location.line, n.location.end_line], (n) => n.id);
}

export function fallbackFunction(entry, line) {
  return smallest(entry.functions ?? [], line, (f) => [f.line, f.end_line], (f) => f.qualname);
}

export function sourceLines(text) {
  const lines = text.split("\n");
  if (lines[lines.length - 1] === "") lines.pop();
  return lines;
}
