"""Versioned JSON-lines engine protocol. stdin/stdout only; no HTTP or GUI dependencies."""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from pyflowcharts.backends.callgraph import to_callgraph_dot
from pyflowcharts.backends.dot import to_dot
from pyflowcharts.desktop.layout import LayoutError, graphviz_layout
from pyflowcharts.explorer.workspace import Snapshot, Workspace, snapshot_json
from pyflowcharts.ir import ChartOptions

PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 1024 * 1024
_NEWLINES = ("\n", b"\n")
# Python keeps undecodable POSIX file-name bytes as lone surrogates, which UTF-8 cannot encode.
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


class ProtocolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _error(request_id: int | None, code: str, message: str) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "id": request_id,
        "ok": False,
        "error": {"code": code, "message": message},
    }


def _snapshot(snapshot: Snapshot) -> dict[str, Any]:
    return snapshot_json(snapshot) | {
        "documents": [
            {"document": dataclasses.asdict(doc), "source_text": result.source_text}
            for doc, result in zip(snapshot.documents, snapshot.results, strict=True)
        ]
    }


class Session:
    """A persistent workspace and a layout cache, owned by one protocol reader."""

    def __init__(self, *, layout: Callable[[str], dict[str, Any]] = graphviz_layout) -> None:
        self._workspace: Workspace | None = None
        self._layout = layout
        self._cache: dict[tuple[int | None, str], dict[str, Any]] = {}

    def request(self, payload: Any) -> dict[str, Any]:
        request_id = None
        try:
            if not isinstance(payload, dict):
                raise ProtocolError("invalid_request", "Expected an object")
            candidate = payload.get("id")
            if type(candidate) is int and 0 <= candidate <= 2**53 - 1:
                request_id = candidate
            if request_id is None:
                raise ProtocolError("invalid_request", "id must be a non-negative safe integer")
            version = payload.get("protocol_version")
            if type(version) is not int:
                raise ProtocolError("invalid_request", "protocol_version must be an integer")
            if version != PROTOCOL_VERSION:
                raise ProtocolError("unsupported_protocol", "Expected desktop protocol version 1")
            method, params = payload.get("method"), payload.get("params", {})
            if not isinstance(method, str) or not isinstance(params, dict):
                raise ProtocolError("invalid_request", "Expected method string and params object")
            result = self._dispatch(method, params)
        except ProtocolError as error:
            return _error(request_id, error.code, str(error))
        except LayoutError as error:
            return _error(request_id, "layout_error", str(error))
        except Exception as error:  # noqa: BLE001 - one failed request must not end the session
            return _error(request_id, "internal_error", f"{type(error).__name__}: {error}")
        return {
            "protocol_version": PROTOCOL_VERSION,
            "id": request_id,
            "ok": True,
            "result": result,
        }

    def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "open": {"paths"},
            "refresh": set(),
            "graph": {"generation", "document", "qualname"},
        }
        if method in allowed and (unknown := params.keys() - allowed[method]):
            raise ProtocolError(
                "invalid_request", f"Unknown parameters: {', '.join(sorted(unknown))}"
            )
        match method:
            case "open":
                paths = params.get("paths")
                if (
                    not isinstance(paths, list)
                    or not paths
                    or any(not isinstance(p, str) or not p or "\0" in p for p in paths)
                ):
                    raise ProtocolError(
                        "invalid_request", "paths must be a non-empty array of paths"
                    )
                self._workspace = Workspace([Path(p) for p in paths], [], ChartOptions())
                self._cache.clear()
                return {"snapshot": _snapshot(self._workspace.current())}
            case "refresh":
                workspace = self._require_workspace()
                if not workspace.refresh():
                    return {"changed": False}
                self._cache.clear()
                return {"changed": True, "snapshot": _snapshot(workspace.current())}
            case "graph":
                return self._graph(params)
            case _:
                raise ProtocolError("unknown_method", f"Unknown method: {method}")

    def _require_workspace(self) -> Workspace:
        if self._workspace is None:
            raise ProtocolError("no_workspace", "Open files or a directory first")
        return self._workspace

    def _graph(self, params: dict[str, Any]) -> dict[str, Any]:
        snapshot = self._require_workspace().current()
        generation = params.get("generation")
        if type(generation) is not int:
            raise ProtocolError("invalid_request", "generation must be an integer")
        if generation != snapshot.generation:
            raise ProtocolError(
                "stale_generation", "The workspace changed; request its current graph"
            )
        if "document" not in params:
            raise ProtocolError("invalid_request", "document is required (null means call graph)")
        index = params["document"]
        qualname = params.get("qualname", "")
        if index is not None and (
            type(index) is not int or not isinstance(qualname, str) or not qualname
        ):
            raise ProtocolError("invalid_request", "Expected document integer and qualname string")
        key = (index, qualname if index is not None else "")
        if key not in self._cache:
            if index is None:
                dot_source = to_callgraph_dot(list(snapshot.documents))
            else:
                if not 0 <= index < len(snapshot.documents):
                    raise ProtocolError("not_found", "Document not found")
                doc = snapshot.documents[index]
                charts = [*doc.functions, *([doc.module] if doc.module is not None else [])]
                chart = next((c for c in charts if c.qualname == qualname), None)
                if chart is None:
                    raise ProtocolError("not_found", "Chart not found")
                dot_source = to_dot(chart)
            self._cache[key] = self._layout(dot_source)
        return {"generation": snapshot.generation, "layout": self._cache[key]}


def _frames(input_stream: BinaryIO | TextIO) -> Iterator[bytes | str | None]:
    """Yield each request line without its newline; None for an oversized line, drained."""
    while line := input_stream.readline(MAX_REQUEST_BYTES + 2):
        body = line[:-1] if line[-1:] in _NEWLINES else line
        size = len(body) if isinstance(body, bytes) else len(body.encode("utf-8", "surrogatepass"))
        if size <= MAX_REQUEST_BYTES:
            yield body
            continue
        while line and line[-1:] not in _NEWLINES:
            line = input_stream.readline(MAX_REQUEST_BYTES + 2)
        yield None


def _respond(session: Session, body: bytes | str | None) -> dict[str, Any]:
    if body is None:
        return _error(None, "invalid_request", "Request exceeds 1 MiB")
    try:
        payload = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    except (ValueError, RecursionError):
        return _error(None, "invalid_request", "Expected one UTF-8 JSON object per line")
    return session.request(payload)


def _encode(response: dict[str, Any]) -> str:
    text = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
    return _LONE_SURROGATE.sub(lambda match: f"\\u{ord(match[0]):04x}", text)


def serve(
    input_stream: BinaryIO | TextIO, output_stream: TextIO, session: Session | None = None
) -> None:
    """One response per line, including malformed requests. EOF shuts down the worker."""
    session = session or Session()
    for body in _frames(input_stream):
        output_stream.write(_encode(_respond(session, body)) + "\n")
        output_stream.flush()
