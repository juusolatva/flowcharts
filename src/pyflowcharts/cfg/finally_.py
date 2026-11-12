"""``try``/``except``/``finally`` handling for the chart builder.

Every node inside a ``try`` body raises into an ``ExceptionScope``: straight to the handler
nodes, or into a pending frontier when the exception must run the finally body first.

A ``finally`` body is drawn once per path that runs it: the normal path, and one copy per
pending ``break``/``continue``/``return``/exception that left the ``try`` body, so each copy
continues to its own target (the next statement, the loop exit, the loop head, ``end`` or
the enclosing handlers). Copies nothing reaches are not drawn.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING

from pyflowcharts.cfg.model import Try
from pyflowcharts.ir import EXCEPTION_LABEL, Edge, NodeKind

if TYPE_CHECKING:
    from pyflowcharts.cfg.builder import ChartBuilder, Frontier


@dataclass
class ExceptionScope:
    """Where exceptions raised by the nodes of a block go: straight to handler nodes, or
    into a pending frontier that later feeds a ``finally (exception)`` copy."""

    handler_ids: list[str]
    pending: Frontier | None

    def attach(self, builder: ChartBuilder, node_ids: list[str]) -> None:
        """Add an ``exception`` edge from each node to every target."""
        for source_id in node_ids:
            if self.handler_ids:
                for handler_id in self.handler_ids:
                    builder.edges.append(Edge(source_id, handler_id, EXCEPTION_LABEL))
            elif self.pending is not None:
                self.pending.append((source_id, EXCEPTION_LABEL))

    def propagate(self, builder: ChartBuilder, frontier: Frontier) -> None:
        """Continue an exception leaving a ``finally (exception)`` copy. Its last node raised
        into this scope already (it is a statement), so it gets no second edge."""
        self.attach(builder, [s for s, _ in frontier if not self._has_edge_from(builder, s)])

    def _has_edge_from(self, builder: ChartBuilder, source_id: str) -> bool:
        if self.handler_ids:
            targets = set(self.handler_ids)
            return any(e.source == source_id and e.target in targets for e in builder.edges)
        return self.pending is not None and (source_id, EXCEPTION_LABEL) in self.pending


@dataclass
class FinallyContext:
    loop_depth: int  # len(builder.loops) when the `try` began
    # Paths that must run the finally body first, one copy of it per kind.
    breaks: Frontier = field(default_factory=list)
    continues: Frontier = field(default_factory=list)
    returns: Frontier = field(default_factory=list)
    exceptions: Frontier = field(default_factory=list)


def emit_try(builder: ChartBuilder, stmt: Try, frontier: Frontier) -> Frontier:
    try_id = builder.add_node(stmt.loc, NodeKind.PROCESS, "try")
    builder.connect(frontier, try_id)
    context = FinallyContext(len(builder.loops))
    has_finally = stmt.finalbody is not None
    if has_finally:
        builder.pending.append(context)
    # Handler nodes are created after the body (to keep node order), but their IDs are
    # known up front so body nodes can point at them. Without handlers (so with a
    # `finally`), body exceptions run the `finally (exception)` copy instead.
    handler_ids = [builder.node_id(handler.loc) for handler in stmt.handlers]
    to_finally = ExceptionScope([], context.exceptions)
    body_scope = ExceptionScope(handler_ids, None) if handler_ids else to_finally
    # Exceptions in `else` and in handlers are not caught by this `try`: they run its
    # finally copy if there is one, else they belong to the enclosing scope.
    after_scope = to_finally if has_finally else None
    try:
        with builder.exception_scope(body_scope):
            normal = builder.block(stmt.body, [(try_id, None)])
        with builder.exception_scope(after_scope):
            normal = builder.block(stmt.orelse, normal)
            for handler in stmt.handlers:
                handler_id = builder.add_node(handler.loc, NodeKind.PROCESS, handler.label)
                normal += builder.block(handler.body, [(handler_id, None)])
    finally:
        if has_finally:
            builder.pending.pop()
    if not has_finally:
        return normal

    # Every copy, the plain one included, is drawn only when some path reaches it.
    result = _finally_copy(builder, stmt, normal, "finally") if normal else []
    # Transfers run their own copy of the finally body, then continue the transfer (which
    # outer `finally` blocks, loops and handlers route in turn). A finally body that ends
    # the path itself (e.g. its own `continue`) yields an empty frontier and overrides it.
    routes: tuple[tuple[str, Frontier, Callable[[Frontier], None]], ...] = (
        ("break", context.breaks, partial(builder.route_break, loc=stmt.loc)),
        ("continue", context.continues, partial(builder.route_continue, loc=stmt.loc)),
        ("return", context.returns, builder.route_return),
        ("exception", context.exceptions, builder.route_exception),
    )
    for kind, pending, route in routes:
        if pending:
            saved = builder.copy_suffix
            # Name the owning `try`, so copy paths through nested try blocks stay unique.
            builder.copy_suffix += f"~{kind}@L{stmt.loc.line}C{stmt.loc.column}"
            try:
                route(_finally_copy(builder, stmt, pending, f"finally ({kind})"))
            finally:
                builder.copy_suffix = saved
    return result


def _finally_copy(builder: ChartBuilder, stmt: Try, entry: Frontier, label: str) -> Frontier:
    assert stmt.finalbody is not None
    fin_id = builder.add_node(stmt.loc, NodeKind.PROCESS, label, suffix="~finally")
    builder.connect(entry, fin_id)
    return builder.block(stmt.finalbody, [(fin_id, None)])
