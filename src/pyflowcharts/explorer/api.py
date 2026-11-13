"""Pure request -> response logic for the explorer's ``/api/*`` routes (no sockets)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import unquote

from pyflowcharts.backends.callgraph import to_callgraph_dot
from pyflowcharts.backends.dot import to_dot
from pyflowcharts.explorer.render import RenderError, svg
from pyflowcharts.explorer.workspace import Snapshot, snapshot_json
from pyflowcharts.ir import MODULE_QUALNAME, Chart, Document
from pyflowcharts.serialize import to_json

TEXT = "text/plain; charset=utf-8"
JSON = "application/json; charset=utf-8"
SVG = "image/svg+xml"


@dataclass(frozen=True)
class Response:
    status: int
    content_type: str
    body: bytes


def _text(status: int, message: str) -> Response:
    return Response(status, TEXT, message.encode("utf-8"))


NOT_FOUND = _text(404, "Not Found\n")
CONFLICT = _text(409, "Conflict\n")


def handle(
    raw_path: str,
    query: dict[str, list[str]],
    snapshot: Snapshot,
    render: Callable[[str], bytes] = svg,
) -> Response:
    """Answer one API request. ``raw_path`` is the still percent-encoded path after ``/api/``."""
    match raw_path.split("/"):
        case ["state"]:
            return Response(200, JSON, json.dumps(snapshot_json(snapshot)).encode("utf-8"))
        case ["svg", "callgraph"]:
            kind, index, segment = "callgraph", "", ""
        case ["document" | "source" as kind, index]:
            segment = ""
        case ["svg", "chart", index, segment]:
            kind = "chart"
        case _:
            return NOT_FOUND
    if query.get("g") != [str(snapshot.generation)]:
        return CONFLICT
    if kind == "callgraph":
        return _cached(snapshot, ("callgraph",), lambda: to_callgraph_dot(_docs(snapshot)), render)
    i = _document_index(index, snapshot)
    if i is None:
        return NOT_FOUND
    match kind:
        case "document":
            return Response(200, JSON, to_json(snapshot.documents[i]).encode("utf-8"))
        case "source":
            return Response(200, TEXT, snapshot.results[i].source_text.encode("utf-8"))
    try:
        qualname = unquote(segment, errors="strict")
    except UnicodeDecodeError:
        return NOT_FOUND
    chart = _find_chart(snapshot, i, qualname)
    if chart is None:
        return NOT_FOUND
    return _cached(snapshot, ("chart", i, qualname), lambda: to_dot(chart), render)


def _document_index(text: str, snapshot: Snapshot) -> int | None:
    """The document index named by ``text``, or ``None``.

    Only ASCII digits count (``str.isdecimal`` alone, like ``\\d``, also accepts other
    scripts' digits). A valid index has at most as many digits as the document count (and
    ``int()`` has a digit limit).
    """
    valid = text.isascii() and text.isdecimal()
    if not valid or len(text) > len(str(len(snapshot.documents))):
        return None
    i = int(text)
    return i if i < len(snapshot.documents) else None


def _docs(snapshot: Snapshot) -> list[Document]:
    return list(snapshot.documents)


def _find_chart(snapshot: Snapshot, i: int, qualname: str) -> Chart | None:
    doc = snapshot.documents[i]
    if qualname == MODULE_QUALNAME:
        return doc.module
    return next((f for f in doc.functions if f.qualname == qualname), None)


def _cached(
    snapshot: Snapshot,
    key: tuple[object, ...],
    dot_source: Callable[[], str],
    render: Callable[[str], bytes],
) -> Response:
    with snapshot.svg_lock:
        hit = snapshot.svg_cache.get(key)
    if hit is None:
        try:
            hit = render(dot_source())
        except RenderError as error:
            return _text(500, str(error))
        with snapshot.svg_lock:
            snapshot.svg_cache[key] = hit
    return Response(200, SVG, hit)
