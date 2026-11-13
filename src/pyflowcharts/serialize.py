"""JSON (de)serialization of the IR. The JSON format is versioned by ``SCHEMA_VERSION``."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from pyflowcharts.ir import (
    Chart,
    Document,
    Edge,
    FunctionChart,
    Node,
    NodeKind,
    Parameter,
    ParamKind,
    SourceLocation,
)

SUPPORTED_VERSIONS = (1, 2)


class UnsupportedSchemaVersionError(ValueError):
    """The JSON document was written with a schema version this code cannot read."""


def to_json(doc: Document) -> str:
    return json.dumps(dataclasses.asdict(doc), indent=2, ensure_ascii=False) + "\n"


def from_json(text: str) -> Document:
    data = json.loads(text)
    version = data.get("schema_version")
    if version not in SUPPORTED_VERSIONS:
        raise UnsupportedSchemaVersionError(
            f"unsupported schema_version {version!r} (expected 1 or 2)"
        )
    module = data.get("module")  # absent in version 1
    return Document(
        source=data["source"],
        language=data["language"],
        functions=[_function_chart(c) for c in data["functions"]],
        module=None if module is None else _module_chart(module),
        schema_version=version,
    )


def _location(data: dict[str, Any] | None) -> SourceLocation | None:
    return None if data is None else SourceLocation(**data)


def _module_chart(data: dict[str, Any]) -> Chart:
    return Chart(
        qualname=data["qualname"],
        location=SourceLocation(**data["location"]),
        nodes=_nodes(data),
        edges=_edges(data),
    )


def _function_chart(data: dict[str, Any]) -> FunctionChart:
    return FunctionChart(
        qualname=data["qualname"],
        location=SourceLocation(**data["location"]),
        nodes=_nodes(data),
        edges=_edges(data),
        name=data["name"],
        is_async=data["is_async"],
        parameters=[
            Parameter(p["name"], p["annotation"], p["default"], ParamKind(p["kind"]))
            for p in data["parameters"]
        ],
        returns=data["returns"],
    )


def _nodes(data: dict[str, Any]) -> list[Node]:
    return [
        Node(n["id"], NodeKind(n["kind"]), n["label"], _location(n["location"]))
        for n in data["nodes"]
    ]


def _edges(data: dict[str, Any]) -> list[Edge]:
    return [Edge(e["source"], e["target"], e["label"]) for e in data["edges"]]
