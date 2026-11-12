"""``try``/``except``/``finally`` handling for the chart builder.

A ``finally`` body is drawn once per path that runs it: the normal path, and one copy
per pending ``break``/``continue`` that left the ``try`` body, so each copy continues
to its own target (the next statement, the loop exit or the loop head).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyflowcharts.cfg.model import Try
from pyflowcharts.ir import Edge, NodeKind

if TYPE_CHECKING:
    from pyflowcharts.cfg.builder import ChartBuilder, Frontier


@dataclass
class ExceptionScope:
    """Where exceptions raised by the nodes of a block go: straight to handler nodes, or
    into a pending frontier that later feeds a ``finally (exception)`` copy."""

    handler_ids: list[str]
    pending: Frontier | None

    def attach(self, builder: ChartBuilder, frontier: Frontier) -> None:
        if self.handler_ids:
            for source_id, label in frontier:
                for handler_id in self.handler_ids:
                    builder.edges.append(Edge(source_id, handler_id, label))
        elif self.pending is not None:
            self.pending.extend(frontier)


@dataclass
class FinallyContext:
    loop_depth: int  # len(builder.loops) when the `try` began
    breaks: Frontier  # pending `break`s that must run the finally body first
    continues: Frontier  # pending `continue`s that must run the finally body first


def emit_try(builder: ChartBuilder, stmt: Try, frontier: Frontier) -> Frontier:
    try_id = builder.add_node(stmt.loc, NodeKind.PROCESS, "try")
    builder.connect(frontier, try_id)
    context = FinallyContext(len(builder.loops), [], [])
    if stmt.finalbody is not None:
        builder.pending.append(context)
    # Handler nodes are created after the body (to keep node order), but their IDs are
    # known up front so body nodes can point at them.
    handler_ids = [builder.node_id(handler.loc) for handler in stmt.handlers]
    body_scope = ExceptionScope(handler_ids, None) if handler_ids else None
    try:
        with builder.exception_scope(body_scope):
            normal = builder.block(stmt.body, [(try_id, None)])
        normal = builder.block(stmt.orelse, normal)
        for handler in stmt.handlers:
            handler_id = builder.add_node(handler.loc, NodeKind.PROCESS, handler.label)
            normal += builder.block(handler.body, [(handler_id, None)])
    finally:
        if stmt.finalbody is not None:
            builder.pending.pop()
    if stmt.finalbody is None:
        return normal

    result = _finally_copy(builder, stmt, normal, "finally")
    # Loop transfers run their own copy of the finally body, then continue the transfer
    # (which outer `finally` blocks and loops route in turn). A finally body that ends
    # the path itself (e.g. its own `continue`) yields an empty frontier and overrides it.
    for kind, pending, route in (
        ("break", context.breaks, builder.route_break),
        ("continue", context.continues, builder.route_continue),
    ):
        if pending:
            saved = builder.copy_suffix
            # Name the owning `try`, so copy paths through nested try blocks stay unique.
            builder.copy_suffix += f"~{kind}@L{stmt.loc.line}C{stmt.loc.column}"
            try:
                route(_finally_copy(builder, stmt, pending, f"finally ({kind})"), stmt.loc)
            finally:
                builder.copy_suffix = saved
    return result


def _finally_copy(builder: ChartBuilder, stmt: Try, entry: Frontier, label: str) -> Frontier:
    assert stmt.finalbody is not None
    fin_id = builder.add_node(stmt.loc, NodeKind.PROCESS, label, suffix="~finally")
    builder.connect(entry, fin_id)
    return builder.block(stmt.finalbody, [(fin_id, None)])
