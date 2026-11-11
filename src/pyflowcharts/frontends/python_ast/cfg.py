"""Build a function's control-flow graph (flowchart nodes and edges) from its AST.

The builder threads a *frontier* through the statements: the list of pending
``(node_id, edge_label)`` pairs whose outgoing edge should point at the next node.
A statement that ends the path (``return``, ``raise``, ``break``, ``continue``)
returns an empty frontier.
"""

from __future__ import annotations

import ast

from pyflowcharts.ir import ChartOptions, Edge, Node, NodeKind, SourceLocation
from pyflowcharts.labels import shorten

Frontier = list[tuple[str, str | None]]

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def location_of(node: ast.stmt | ast.excepthandler) -> SourceLocation:
    return SourceLocation(
        line=node.lineno,
        column=node.col_offset,
        end_line=node.end_lineno if node.end_lineno is not None else node.lineno,
        end_column=node.end_col_offset if node.end_col_offset is not None else node.col_offset,
    )


def start_label_for(func: FunctionNode, options: ChartOptions) -> str:
    prefix = "async " if isinstance(func, ast.AsyncFunctionDef) else ""
    if not options.show_parameters:
        return f"{prefix}def {func.name}(...)"
    label = f"{prefix}def {func.name}({ast.unparse(func.args)})"
    if func.returns is not None:
        label += f" -> {ast.unparse(func.returns)}"
    return label


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _contains_call(node: ast.AST | None) -> bool:
    return node is not None and any(isinstance(n, ast.Call) for n in ast.walk(node))


class CfgBuilder:
    def __init__(self, qualname: str, options: ChartOptions) -> None:
        self.qualname = qualname
        self.options = options
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self._end_id = f"{qualname}#end"
        self._copy_suffix = ""

    def build(self, func: FunctionNode, start_label: str) -> tuple[list[Node], list[Edge]]:
        start_id = f"{self.qualname}#start"
        self.nodes.append(
            Node(start_id, NodeKind.START, self._label(start_label), location_of(func))
        )
        self.nodes.append(Node(self._end_id, NodeKind.END, "end", None))
        body = func.body[1:] if func.body and _is_docstring(func.body[0]) else func.body
        frontier = self._block(body, [(start_id, None)])
        self._connect(frontier, self._end_id)
        return self.nodes, self.edges

    # -- statement handling -------------------------------------------------

    def _block(self, stmts: list[ast.stmt], frontier: Frontier) -> Frontier:
        for stmt in stmts:
            frontier = self._stmt(stmt, frontier)
        return frontier

    def _stmt(self, stmt: ast.stmt, frontier: Frontier) -> Frontier:
        match stmt:
            case ast.Pass() | ast.Global() | ast.Nonlocal():
                return frontier
            case ast.Expr(value=ast.Constant(value=value)) if value is Ellipsis:
                return frontier
            case ast.Assign() | ast.AugAssign() | ast.AnnAssign() if not self._shows(stmt):
                return frontier
            case ast.Return(value=value):
                if value is None or not self.options.show_returns:
                    label = "return"
                else:
                    label = f"return {ast.unparse(value)}"
                return self._terminal(stmt, frontier, NodeKind.RETURN, label)
            case ast.Raise():
                return self._terminal(stmt, frontier, NodeKind.RAISE, ast.unparse(stmt))
            case ast.If():
                return self._if(stmt, frontier)
            case ast.Match():
                return self._match(stmt, frontier)
            case _:
                return self._chain(stmt, frontier, NodeKind.PROCESS, ast.unparse(stmt))

    def _if(self, stmt: ast.If, frontier: Frontier) -> Frontier:
        node_id = self._add_node(stmt, NodeKind.DECISION, f"if {ast.unparse(stmt.test)}")
        self._connect(frontier, node_id)
        out = self._block(stmt.body, [(node_id, "True")])
        if stmt.orelse:
            return out + self._block(stmt.orelse, [(node_id, "False")])
        return out + [(node_id, "False")]

    def _match(self, stmt: ast.Match, frontier: Frontier) -> Frontier:
        node_id = self._add_node(stmt, NodeKind.DECISION, f"match {ast.unparse(stmt.subject)}")
        self._connect(frontier, node_id)
        out: Frontier = []
        for case in stmt.cases:
            label = f"case {ast.unparse(case.pattern)}"
            if case.guard is not None:
                label += f" if {ast.unparse(case.guard)}"
            out += self._block(case.body, [(node_id, self._label(label))])
        last = stmt.cases[-1]
        irrefutable = (
            last.guard is None
            and isinstance(last.pattern, ast.MatchAs)
            and last.pattern.pattern is None
        )
        if not irrefutable:
            out.append((node_id, "no match"))
        return out

    def _shows(self, stmt: ast.Assign | ast.AugAssign | ast.AnnAssign) -> bool:
        return self.options.show_variables or _contains_call(stmt.value)

    # -- graph primitives ---------------------------------------------------

    def _chain(self, stmt: ast.stmt, frontier: Frontier, kind: NodeKind, label: str) -> Frontier:
        """Add a node after ``frontier`` and continue from it."""
        node_id = self._add_node(stmt, kind, label)
        self._connect(frontier, node_id)
        return [(node_id, None)]

    def _terminal(self, stmt: ast.stmt, frontier: Frontier, kind: NodeKind, label: str) -> Frontier:
        """Add a node after ``frontier`` that leads straight to ``end``."""
        node_id = self._add_node(stmt, kind, label)
        self._connect(frontier, node_id)
        self._connect([(node_id, None)], self._end_id)
        return []

    def _add_node(
        self,
        stmt: ast.stmt | ast.excepthandler,
        kind: NodeKind,
        label: str,
        suffix: str = "",
    ) -> str:
        node_id = f"{self.qualname}#L{stmt.lineno}C{stmt.col_offset}{suffix}{self._copy_suffix}"
        location = None if suffix else location_of(stmt)
        self.nodes.append(Node(node_id, kind, self._label(label), location))
        return node_id

    def _connect(self, frontier: Frontier, target_id: str) -> None:
        for source_id, label in frontier:
            self.edges.append(Edge(source_id, target_id, label))

    def _label(self, text: str) -> str:
        return shorten(text, self.options.max_label_length)
