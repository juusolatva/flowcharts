"""Build a function's flowchart (nodes and edges) from model statements.

The builder threads a *frontier* through the statements: the list of pending
``(node_id, edge_label)`` pairs whose outgoing edge should point at the next node.
A statement that ends the path (``Terminal``, ``Break``, ``Continue``) returns an
empty frontier.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyflowcharts.cfg.finally_ import FinallyContext, emit_try
from pyflowcharts.cfg.model import (
    Block,
    Branch,
    Break,
    Continue,
    Loop,
    Step,
    Stmt,
    Terminal,
    Try,
)
from pyflowcharts.ir import ChartOptions, Edge, Node, NodeKind, SourceLocation
from pyflowcharts.labels import shorten

Frontier = list[tuple[str, str | None]]


class StrayLoopTransfer(Exception):
    """A ``break``/``continue`` outside any loop (a syntax error the frontend reports)."""

    def __init__(self, kind: str, loc: SourceLocation) -> None:
        super().__init__(kind, loc)
        self.kind = kind
        self.loc = loc


@dataclass
class LoopContext:
    loop_id: str
    breaks: Frontier  # paths leaving the loop via `break`


def build_chart(
    qualname: str,
    start_label: str,
    start_loc: SourceLocation,
    body: Block,
    options: ChartOptions,
) -> tuple[list[Node], list[Edge]]:
    builder = ChartBuilder(qualname, options)
    start_id = f"{qualname}#start"
    builder.nodes.append(Node(start_id, NodeKind.START, builder.label(start_label), start_loc))
    builder.nodes.append(Node(builder.end_id, NodeKind.END, "end", None))
    builder.connect(builder.block(body, [(start_id, None)]), builder.end_id)
    return builder.nodes, builder.edges


class ChartBuilder:
    def __init__(self, qualname: str, options: ChartOptions) -> None:
        self.qualname = qualname
        self.options = options
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self.end_id = f"{qualname}#end"
        self.loops: list[LoopContext] = []
        self.pending: list[FinallyContext] = []
        self.copy_suffix = ""
        self._reveal = False  # show hidden steps, because the block has nothing else

    # -- statements -----------------------------------------------------------

    def block(self, stmts: Block, frontier: Frontier) -> Frontier:
        saved = self._reveal
        # A block made only of hidden steps would look empty (e.g. an `if` whose True
        # and False edges meet at the same node), so it shows them anyway.
        self._reveal = not any(self._visible(stmt) for stmt in stmts)
        try:
            for stmt in stmts:
                frontier = self._stmt(stmt, frontier)
        finally:
            self._reveal = saved
        return frontier

    def _visible(self, stmt: Stmt) -> bool:
        """Whether the statement gets a node under the normal (non-reveal) rules."""
        return not (isinstance(stmt, Step) and stmt.hidden) or self.options.show_variables

    def _stmt(self, stmt: Stmt, frontier: Frontier) -> Frontier:
        match stmt:
            case Step(hidden=True) if not (self._reveal or self.options.show_variables):
                return frontier
            case Step(label=label, loc=loc, body=body):
                node_id = self.add_node(loc, NodeKind.PROCESS, label)
                self.connect(frontier, node_id)
                return self.block(body, [(node_id, None)])
            case Terminal(kind=kind, label=label, loc=loc):
                node_id = self.add_node(loc, kind, label)
                self.connect(frontier, node_id)
                self.connect([(node_id, None)], self.end_id)
                return []
            case Branch():
                return self._branch(stmt, frontier)
            case Loop():
                return self._loop(stmt, frontier)
            case Break(loc=loc):
                self.route_break(frontier, loc)
                return []
            case Continue(loc=loc):
                self.route_continue(frontier, loc)
                return []
            case Try():
                return emit_try(self, stmt, frontier)
        raise TypeError(f"unknown statement {stmt!r}")

    def _branch(self, stmt: Branch, frontier: Frontier) -> Frontier:
        node_id = self.add_node(stmt.loc, NodeKind.DECISION, stmt.label)
        self.connect(frontier, node_id)
        out: Frontier = []
        for arm in stmt.arms:
            out += self.block(arm.body, [(node_id, self.label(arm.edge_label))])
        if stmt.default is not None:
            out.append((node_id, stmt.default))
        return out

    def _loop(self, stmt: Loop, frontier: Frontier) -> Frontier:
        node_id = self.add_node(stmt.loc, NodeKind.LOOP, stmt.label)
        self.connect(frontier, node_id)
        context = LoopContext(node_id, [])
        self.loops.append(context)
        try:
            body_end = self.block(stmt.body, [(node_id, stmt.enter)])
        finally:
            self.loops.pop()
        self.connect(body_end, node_id)
        out: Frontier = [(node_id, stmt.exit)] if stmt.exit is not None else []
        out = self.block(stmt.orelse, out)
        return out + context.breaks

    def route_break(self, frontier: Frontier, loc: SourceLocation) -> None:
        if not self.loops:
            raise StrayLoopTransfer("break", loc)
        if (pending := self._pending_finally()) is not None:
            pending.breaks.extend(frontier)
        else:
            self._innermost_loop("break", loc).breaks.extend(frontier)

    def route_continue(self, frontier: Frontier, loc: SourceLocation) -> None:
        if not self.loops:
            raise StrayLoopTransfer("continue", loc)
        if (pending := self._pending_finally()) is not None:
            pending.continues.extend(frontier)
        else:
            self.connect(frontier, self._innermost_loop("continue", loc).loop_id)

    def _pending_finally(self) -> FinallyContext | None:
        """The ``try … finally`` a loop transfer must pass through, if it is inside the loop."""
        if self.pending and self.pending[-1].loop_depth == len(self.loops):
            return self.pending[-1]
        return None

    def _innermost_loop(self, kind: str, loc: SourceLocation) -> LoopContext:
        if not self.loops:
            raise StrayLoopTransfer(kind, loc)
        return self.loops[-1]

    # -- graph primitives -----------------------------------------------------

    def add_node(self, loc: SourceLocation, kind: NodeKind, label: str, suffix: str = "") -> str:
        node_id = f"{self.qualname}#L{loc.line}C{loc.column}{suffix}{self.copy_suffix}"
        self.nodes.append(Node(node_id, kind, self.label(label), None if suffix else loc))
        return node_id

    def connect(self, frontier: Frontier, target_id: str) -> None:
        for source_id, label in frontier:
            self.edges.append(Edge(source_id, target_id, label))

    def label(self, text: str) -> str:
        return shorten(text, self.options.max_label_length)
