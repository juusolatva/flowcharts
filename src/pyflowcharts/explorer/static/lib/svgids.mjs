export function nodeIdFromTitle(text) {
  return text.trim();
}

// Call-graph node titles are "{doc}#{qualname}"; qualnames may contain "#".
export function splitCallgraphId(id) {
  const at = id.indexOf("#");
  return { doc: Number(id.slice(0, at)), qualname: id.slice(at + 1) };
}
