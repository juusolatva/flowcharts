// Hash routes: #/ (call graph), #/chart/<key segments>/<qualname>, #/file/<key segments>.
// Each key segment is encoded separately, so "a/b" stays two path segments.
const CALLGRAPH = { view: "callgraph" };

function decodeSegments(segments) {
  if (segments.length === 0 || segments.some((s) => !s)) return null;
  return segments.map(decodeURIComponent);
}

export function parseHash(hash) {
  try {
    const [view, ...rest] = String(hash ?? "").replace(/^#\/?/, "").split("/");
    if (view === "chart") {
      const decoded = decodeSegments(rest);
      if (decoded && decoded.length >= 2) {
        return { view, key: decoded.slice(0, -1).join("/"), qualname: decoded.at(-1) };
      }
    } else if (view === "file") {
      const decoded = decodeSegments(rest);
      if (decoded) return { view, key: decoded.join("/") };
    }
  } catch (error) {
    if (!(error instanceof URIError)) throw error;
  }
  return { ...CALLGRAPH };
}

const encodeKey = (key) => key.split("/").map(encodeURIComponent).join("/");

export function formatHash(route) {
  switch (route.view) {
    case "chart":
      return `#/chart/${encodeKey(route.key)}/${encodeURIComponent(route.qualname)}`;
    case "file":
      return `#/file/${encodeKey(route.key)}`;
    default:
      return "#/";
  }
}
