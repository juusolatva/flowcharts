"""Mermaid flowchart backend (renders natively on GitHub, in many docs tools and editors)."""

from __future__ import annotations

from pyflowcharts.ir import EXCEPTION_LABEL, FunctionChart, NodeKind

# "{t}" is replaced by the escaped label.
SHAPES: dict[NodeKind, str] = {
    NodeKind.START: '(["{t}"])',
    NodeKind.END: '(["{t}"])',
    NodeKind.PROCESS: '["{t}"]',
    NodeKind.DECISION: '{{"{t}"}}',
    NodeKind.LOOP: '{{{{"{t}"}}}}',
    NodeKind.RETURN: '[/"{t}"/]',
    NodeKind.RAISE: '>"{t}"]',
}

# Mermaid reads "#<code>;" as an entity, so "#" itself must be escaped first.
_ESCAPES = (("#", "#35;"), ('"', "#34;"), ("<", "#60;"), (">", "#62;"))


def _escape(text: str) -> str:
    for char, entity in _ESCAPES:
        text = text.replace(char, entity)
    return text


def to_mermaid(chart: FunctionChart) -> str:
    ids = {node.id: f"n{i}" for i, node in enumerate(chart.nodes)}
    lines = ["flowchart TD"]
    for node in chart.nodes:
        lines.append(f"    {ids[node.id]}" + SHAPES[node.kind].format(t=_escape(node.label)))
    for edge in chart.edges:
        if edge.label is None:
            arrow = "-->"
        else:
            line = "-.->" if edge.label == EXCEPTION_LABEL else "-->"
            arrow = f'{line}|"{_escape(edge.label)}"|'
        lines.append(f"    {ids[edge.source]} {arrow} {ids[edge.target]}")
    return "\n".join(lines) + "\n"
