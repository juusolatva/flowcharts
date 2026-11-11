"""Graphviz backend: DOT source, plus SVG/PNG rendering through the ``dot`` executable."""

from __future__ import annotations

from typing import Literal

import graphviz

from pyflowcharts.ir import FunctionChart, NodeKind

SHAPES: dict[NodeKind, str] = {
    NodeKind.START: "oval",
    NodeKind.END: "oval",
    NodeKind.PROCESS: "box",
    NodeKind.DECISION: "diamond",
    NodeKind.LOOP: "hexagon",
    NodeKind.RETURN: "parallelogram",
    NodeKind.RAISE: "octagon",
}


def to_digraph(chart: FunctionChart) -> graphviz.Digraph:
    graph = graphviz.Digraph(
        chart.qualname,
        graph_attr={"rankdir": "TB"},
        node_attr={"fontname": "Helvetica"},
        edge_attr={"fontname": "Helvetica"},
    )
    for node in chart.nodes:
        attrs = {"shape": SHAPES[node.kind]}
        if node.location is not None:
            attrs["tooltip"] = f"line {node.location.line}"
        # escape() keeps backslashes in source text literal instead of DOT escapes like \n.
        graph.node(node.id, label=graphviz.escape(node.label), **attrs)
    for edge in chart.edges:
        if edge.label is None:
            graph.edge(edge.source, edge.target)
        else:
            graph.edge(edge.source, edge.target, label=graphviz.escape(edge.label))
    return graph


def to_dot(chart: FunctionChart) -> str:
    return to_digraph(chart).source


def render(chart: FunctionChart, fmt: Literal["svg", "png"]) -> bytes:
    """Render with Graphviz. Raises ``graphviz.ExecutableNotFound`` if ``dot`` is missing."""
    return to_digraph(chart).pipe(format=fmt)
