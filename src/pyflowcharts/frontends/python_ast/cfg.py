"""Convert a function's ``ast`` body into model statements for the shared CFG builder."""

from __future__ import annotations

import ast

from pyflowcharts.cfg.model import (
    Arm,
    Block,
    Branch,
    Break,
    Continue,
    Handler,
    Loop,
    Step,
    Stmt,
    Terminal,
    Try,
)
from pyflowcharts.frontends.python_ast.source import SourceText
from pyflowcharts.ir import ChartOptions, NodeKind, SourceLocation

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def location_of(node: ast.stmt | ast.excepthandler) -> SourceLocation:
    return SourceLocation(
        line=node.lineno,
        column=node.col_offset,
        end_line=node.end_lineno if node.end_lineno is not None else node.lineno,
        end_column=node.end_col_offset if node.end_col_offset is not None else node.col_offset,
    )


def start_label_for(func: FunctionNode, options: ChartOptions) -> str:
    """The signature uses ast.unparse: ``ast.arguments`` has no source position to slice."""
    prefix = "async " if isinstance(func, ast.AsyncFunctionDef) else ""
    if not options.show_parameters:
        return f"{prefix}def {func.name}(...)"
    label = f"{prefix}def {func.name}({ast.unparse(func.args)})"
    if func.returns is not None:
        label += f" -> {ast.unparse(func.returns)}"
    return label


def function_body(func: FunctionNode, source: SourceText, options: ChartOptions) -> Block:
    body = func.body[1:] if func.body and _is_docstring(func.body[0]) else func.body
    return _Converter(source, options).block(body)


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _contains_call(node: ast.AST | None) -> bool:
    return node is not None and any(isinstance(n, ast.Call) for n in ast.walk(node))


class _Converter:
    def __init__(self, source: SourceText, options: ChartOptions) -> None:
        self.source = source
        self.options = options

    def block(self, stmts: list[ast.stmt]) -> Block:
        out: list[Stmt] = []
        for stmt in stmts:
            converted = self.stmt(stmt)
            if converted is not None:
                out.append(converted)
        return tuple(out)

    def stmt(self, stmt: ast.stmt) -> Stmt | None:
        loc = location_of(stmt)
        match stmt:
            case ast.Pass() | ast.Global() | ast.Nonlocal():
                return None
            case ast.Expr(value=ast.Constant(value=value)) if value is Ellipsis:
                return None
            case ast.Assign() | ast.AugAssign() | ast.AnnAssign():
                return Step(self._text(stmt), loc, hidden=not _contains_call(stmt.value))
            case ast.Return(value=value):
                if value is None or not self.options.show_returns:
                    label = "return"
                else:
                    label = f"return {self._text(value)}"
                return Terminal(NodeKind.RETURN, label, loc)
            case ast.Raise():
                return Terminal(NodeKind.RAISE, self._text(stmt), loc)
            case ast.If():
                return self._if(stmt)
            case ast.Match():
                return self._match(stmt)
            case ast.For() | ast.AsyncFor():
                prefix = "async " if isinstance(stmt, ast.AsyncFor) else ""
                label = f"{prefix}for {self._text(stmt.target)} in {self._text(stmt.iter)}"
                return Loop(
                    label, loc, "next", "done", self.block(stmt.body), self.block(stmt.orelse)
                )
            case ast.While():
                always = isinstance(stmt.test, ast.Constant) and bool(stmt.test.value)
                label = f"while {self._text(stmt.test)}"
                exit_label = None if always else "False"
                return Loop(
                    label, loc, "True", exit_label, self.block(stmt.body), self.block(stmt.orelse)
                )
            case ast.Try() | ast.TryStar():
                return self._try(stmt)
            case ast.With() | ast.AsyncWith():
                prefix = "async " if isinstance(stmt, ast.AsyncWith) else ""
                items = ", ".join(self._withitem(item) for item in stmt.items)
                return Step(f"{prefix}with {items}", loc, body=self.block(stmt.body))
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                return Step(start_label_for(stmt, self.options), loc)
            case ast.ClassDef():
                return Step(f"class {stmt.name}", loc)
            case ast.Break():
                return Break(loc)
            case ast.Continue():
                return Continue(loc)
            case _:
                return Step(self._text(stmt), loc)

    def _if(self, stmt: ast.If) -> Branch:
        arms = [Arm("True", self.block(stmt.body))]
        default = None
        if stmt.orelse:
            arms.append(Arm("False", self.block(stmt.orelse)))
        else:
            default = "False"
        return Branch(f"if {self._text(stmt.test)}", location_of(stmt), tuple(arms), default)

    def _match(self, stmt: ast.Match) -> Branch:
        arms = []
        for case in stmt.cases:
            label = f"case {self._text(case.pattern)}"
            if case.guard is not None:
                label += f" if {self._text(case.guard)}"
            arms.append(Arm(label, self.block(case.body)))
        last = stmt.cases[-1]
        irrefutable = (
            last.guard is None
            and isinstance(last.pattern, ast.MatchAs)
            and last.pattern.pattern is None
        )
        default = None if irrefutable else "no match"
        return Branch(f"match {self._text(stmt.subject)}", location_of(stmt), tuple(arms), default)

    def _try(self, stmt: ast.Try | ast.TryStar) -> Try:
        star = "*" if isinstance(stmt, ast.TryStar) else ""
        handlers = []
        for handler in stmt.handlers:
            label = f"except{star}"
            if handler.type is not None:
                label += f" {self._text(handler.type)}"
            if handler.name is not None:
                label += f" as {handler.name}"
            handlers.append(Handler(label, location_of(handler), self.block(handler.body)))
        finalbody = self.block(stmt.finalbody) if stmt.finalbody else None
        return Try(
            location_of(stmt),
            self.block(stmt.body),
            tuple(handlers),
            self.block(stmt.orelse),
            finalbody,
        )

    # -- labels ---------------------------------------------------------------

    def _text(self, node: ast.AST) -> str:
        return self.source.text(node)

    def _withitem(self, item: ast.withitem) -> str:
        text = self._text(item.context_expr)
        if item.optional_vars is not None:
            text += f" as {self._text(item.optional_vars)}"
        return text
