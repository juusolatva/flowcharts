"""JSON (de)serialization of the IR. The JSON format is versioned by ``SCHEMA_VERSION``."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from pyflowcharts.ir import (
    SCHEMA_VERSION,
    Document,
    Edge,
    FunctionChart,
    Node,
    NodeKind,
    Parameter,
    ParamKind,
    SourceLocation,
)


class UnsupportedSchemaVersionError(ValueError):
    """The JSON document was written with a schema version this code cannot read."""


def to_json(doc: Document) -> str:
    return json.dumps(dataclasses.asdict(doc), indent=2, ensure_ascii=False) + "\n"


def from_json(text: str) -> Document:
    data = json.loads(text)
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise UnsupportedSchemaVersionError(
            f"unsupported schema_version {version!r} (expected {SCHEMA_VERSION})"
        )
    return Document(
        source=data["source"],
        language=data["language"],
        functions=[_chart(c) for c in data["functions"]],
        schema_version=version,
    )


def _location(data: dict[str, Any] | None) -> SourceLocation | None:
    return None if data is None else SourceLocation(**data)


def _chart(data: dict[str, Any]) -> FunctionChart:
    location = SourceLocation(**data["location"])
    return FunctionChart(
        qualname=data["qualname"],
        name=data["name"],
        is_async=data["is_async"],
        parameters=[
            Parameter(p["name"], p["annotation"], p["default"], ParamKind(p["kind"]))
            for p in data["parameters"]
        ],
        returns=data["returns"],
        location=location,
        nodes=[
            Node(n["id"], NodeKind(n["kind"]), n["label"], _location(n["location"]))
            for n in data["nodes"]
        ],
        edges=[Edge(e["source"], e["target"], e["label"]) for e in data["edges"]],
    )
