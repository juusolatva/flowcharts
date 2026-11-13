// Hash routes: #/ (call graph), #/chart/<key>/<qualname>, #/file/<key>.
const CALLGRAPH = { view: "callgraph" };

export function parseHash(hash) {
  try {
    const parts = String(hash ?? "").replace(/^#\/?/, "").split("/");
    if (parts[0] === "chart" && parts.length === 3 && parts[1] && parts[2]) {
      return { view: "chart", key: decodeURIComponent(parts[1]), qualname: decodeURIComponent(parts[2]) };
    }
    if (parts[0] === "file" && parts.length === 2 && parts[1]) {
      return { view: "file", key: decodeURIComponent(parts[1]) };
    }
  } catch (error) {
    if (!(error instanceof URIError)) throw error;
  }
  return { ...CALLGRAPH };
}

export function formatHash(route) {
  switch (route.view) {
    case "chart":
      return `#/chart/${encodeURIComponent(route.key)}/${encodeURIComponent(route.qualname)}`;
    case "file":
      return `#/file/${encodeURIComponent(route.key)}`;
    default:
      return "#/";
  }
}
