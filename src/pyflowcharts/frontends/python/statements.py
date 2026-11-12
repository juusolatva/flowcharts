"""Convert tree-sitter statement nodes into model statements for the shared builder."""

from __future__ import annotations

import ast
import warnings

from tree_sitter import Node

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
from pyflowcharts.frontends.python.source import Source
from pyflowcharts.ir import ChartOptions, NodeKind

_SKIPPED = frozenset({"pass_statement", "global_statement", "nonlocal_statement"})
_EXTRAS = frozenset({"comment", "line_continuation"})


def _named(node: Node) -> list[Node]:
    """Named children without the grammar's extras (comments, line continuations), which
    can appear anywhere, including before a statement's expression."""
    return [c for c in node.named_children if c.type not in _EXTRAS]


def convert_body(func: Node, src: Source, options: ChartOptions) -> Block:
    """The function body as model statements, with a leading docstring dropped."""
    block = func.child_by_field_name("body")
    stmts = _named(block) if block is not None else []
    if stmts and _is_docstring(stmts[0]):
        stmts = stmts[1:]
    return _Converter(src, options).stmts(stmts)


def convert_block(block: Node | None, src: Source, options: ChartOptions) -> Block:
    return _Converter(src, options).block(block)


def signature_label(func: Node, src: Source, options: ChartOptions) -> str:
    prefix = "async " if func.children and func.children[0].type == "async" else ""
    name = _field_text(func, "name", src)
    if not options.show_parameters:
        return f"{prefix}def {name}(...)"
    label = f"{prefix}def {name}{_field_text(func, 'parameters', src)}"
    if (returns := func.child_by_field_name("return_type")) is not None:
        label += f" -> {src.source_text(returns)}"
    return label


def always_true(cond: str) -> bool:
    """Whether a ``while`` condition is a single truthy constant (then only ``break`` exits)."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            expr = ast.parse(cond, mode="eval").body
    except (SyntaxError, ValueError):
        return False
    return isinstance(expr, ast.Constant) and bool(expr.value)


def _is_docstring(stmt: Node) -> bool:
    children = _named(stmt)
    if stmt.type != "expression_statement" or len(children) != 1:
        return False
    value = children[0]
    strings = value.named_children if value.type == "concatenated_string" else [value]
    return all(s.type == "string" and _is_plain_string(s) for s in strings)


def _is_plain_string(string: Node) -> bool:
    """Not an f-string or bytes (which ``ast`` does not treat as docstrings)."""
    start = string.children[0].text or b""
    return not any(c in b"fFbB" for c in start.rstrip(b"'\""))


def _contains_call(node: Node | None) -> bool:
    if node is None:
        return False
    if node.type == "call":
        return True
    return any(_contains_call(child) for child in node.children)


def _calls_in_value(assignment: Node) -> bool:
    """Whether the assigned value contains a call. Chained assignments (``a = b = v``) nest
    on the right, and only the final value counts, as with ``ast``."""
    value = assignment.child_by_field_name("right")
    while value is not None and value.type == "assignment":
        value = value.child_by_field_name("right")
    return _contains_call(value)


def _is_type_alias(node: Node) -> bool:
    """A real ``type X = ...`` statement has a name (or ``Name[T]``) on the left."""
    left = node.child_by_field_name("left")
    target = left.named_children[0] if left is not None and left.named_child_count else None
    return target is not None and target.type in ("identifier", "generic_type")


def _field_text(node: Node, field: str, src: Source) -> str:
    child = node.child_by_field_name(field)
    return src.source_text(child) if child is not None else ""


class _Converter:
    def __init__(self, src: Source, options: ChartOptions) -> None:
        self.src = src
        self.options = options

    def block(self, block: Node | None) -> Block:
        return self.stmts(_named(block)) if block is not None else ()

    def stmts(self, nodes: list[Node]) -> Block:
        out: list[Stmt] = []
        for node in nodes:
            converted = self.stmt(node)
            if converted is not None:
                out.append(converted)
        return tuple(out)

    def stmt(self, node: Node) -> Stmt | None:
        loc = self.src.location(node)
        match node.type:
            case "expression_statement":
                return self._expression(node)
            case _ if node.type in _SKIPPED:
                return None
            case "return_statement":
                values = _named(node)
                value = values[0] if values else None
                if value is None or not self.options.show_returns:
                    return Terminal(NodeKind.RETURN, "return", loc)
                return Terminal(NodeKind.RETURN, f"return {self.src.source_text(value)}", loc)
            case "raise_statement":
                return Terminal(NodeKind.RAISE, self.src.source_text(node), loc)
            case "if_statement" | "elif_clause":
                return self._if(node)
            case "match_statement":
                return self._match(node)
            case "for_statement":
                prefix = "async " if node.children[0].type == "async" else ""
                label = f"{prefix}for {self._text(node, 'left')} in {self._text(node, 'right')}"
                return Loop(label, loc, "next", "done", self._body(node), self._else(node))
            case "while_statement":
                cond = self._text(node, "condition")
                exit_label = None if always_true(cond) else "False"
                return Loop(
                    f"while {cond}", loc, "True", exit_label, self._body(node), self._else(node)
                )
            case "try_statement":
                return self._try(node)
            case "with_statement":
                prefix = "async " if node.children[0].type == "async" else ""
                clause = next(c for c in node.children if c.type == "with_clause")
                return Step(
                    f"{prefix}with {self.src.source_text(clause)}", loc, body=self._body(node)
                )
            case "decorated_definition":
                definition = node.child_by_field_name("definition")
                return self.stmt(definition) if definition is not None else None
            case "function_definition":
                return Step(signature_label(node, self.src, self.options), loc)
            case "class_definition":
                return Step(f"class {self._text(node, 'name')}", loc)
            case "type_alias_statement" if not _is_type_alias(node):
                # The grammar reads `type(x).a = v` as a PEP 695 alias; it is an assignment.
                return Step(self.src.source_text(node), loc, hidden=not _calls_in_value(node))
            case "break_statement":
                return Break(loc)
            case "continue_statement":
                return Continue(loc)
            case _:
                return Step(self.src.source_text(node), loc)

    def _expression(self, node: Node) -> Stmt | None:
        loc = self.src.location(node)
        children = _named(node)
        inner = children[0] if len(children) == 1 else None
        match inner.type if inner is not None else None:
            case "ellipsis":
                return None
            case "assignment" | "augmented_assignment":
                return Step(self.src.source_text(node), loc, hidden=not _calls_in_value(inner))
        return Step(self.src.source_text(node), loc)

    def _if(self, node: Node) -> Branch:
        arms = [Arm("True", self.block(node.child_by_field_name("consequence")))]
        default: str | None = "False"
        alternatives = [c for c in node.children if c.type in ("elif_clause", "else_clause")]
        if alternatives:
            default = None
            first = alternatives[0]
            if first.type == "else_clause":
                arms.append(Arm("False", self.block(first.child_by_field_name("body"))))
            else:
                # Each elif is a nested branch; the remaining clauses belong to it.
                nested = self._if_chain(first, alternatives[1:])
                arms.append(Arm("False", (nested,)))
        return Branch(
            f"if {self._text(node, 'condition')}", self.src.location(node), tuple(arms), default
        )

    def _if_chain(self, clause: Node, rest: list[Node]) -> Branch:
        arms = [Arm("True", self.block(clause.child_by_field_name("consequence")))]
        default: str | None = "False"
        if rest:
            default = None
            if rest[0].type == "else_clause":
                arms.append(Arm("False", self.block(rest[0].child_by_field_name("body"))))
            else:
                arms.append(Arm("False", (self._if_chain(rest[0], rest[1:]),)))
        return Branch(
            f"if {self._text(clause, 'condition')}", self.src.location(clause), tuple(arms), default
        )

    def _match(self, node: Node) -> Branch:
        body = node.child_by_field_name("body")
        cases = [
            c for c in (body.named_children if body is not None else []) if c.type == "case_clause"
        ]
        arms = []
        for case in cases:
            patterns = [c for c in case.named_children if c.type == "case_pattern"]
            label = "case " + ", ".join(self.src.source_text(p) for p in patterns)
            if (guard := case.child_by_field_name("guard")) is not None:
                label += f" {self.src.source_text(guard)}"
            arms.append(Arm(label, self.block(case.child_by_field_name("consequence"))))
        default = None if cases and _irrefutable(cases[-1]) else "no match"
        subject = ", ".join(self.src.source_text(c) for c in node.children_by_field_name("subject"))
        return Branch(f"match {subject}", self.src.location(node), tuple(arms), default)

    def _try(self, node: Node) -> Try:
        handlers = []
        orelse: Block = ()
        finalbody: Block | None = None
        for clause in node.children:
            match clause.type:
                case "except_clause" | "except_group_clause":
                    handlers.append(self._handler(clause))
                case "else_clause":
                    orelse = self.block(clause.child_by_field_name("body"))
                case "finally_clause":
                    finalbody = self.block(next(c for c in clause.children if c.type == "block"))
        return Try(self.src.location(node), self._body(node), tuple(handlers), orelse, finalbody)

    def _handler(self, clause: Node) -> Handler:
        parts = []
        for child in clause.children:
            if child.type == ":":
                break
            parts.append(child)
        label = self.src.source_text(parts[0])  # "except"
        rest = parts[1:]
        if rest and rest[0].type == "*":
            label += "*"
            rest = rest[1:]
        if rest:
            label += " " + " ".join(self.src.source_text(c) for c in rest)
        block = next((c for c in clause.children if c.type == "block"), None)
        return Handler(label, self.src.location(clause), self.block(block))

    def _body(self, node: Node) -> Block:
        return self.block(node.child_by_field_name("body"))

    def _else(self, node: Node) -> Block:
        for child in node.children:
            if child.type == "else_clause":
                return self.block(child.child_by_field_name("body"))
        return ()

    def _text(self, node: Node, field: str) -> str:
        return _field_text(node, field, self.src)


def _irrefutable(case: Node) -> bool:
    """A bare capture name, ``_``, or one of those in parentheses, with no guard."""
    if case.child_by_field_name("guard") is not None:
        return False
    patterns = [c for c in case.named_children if c.type == "case_pattern"]
    if len(patterns) != 1 or any(c.type == "," for c in case.children):
        return False  # `case y,:` is a one-element sequence pattern
    return _capture(patterns[0])


def _capture(pattern: Node) -> bool:
    if pattern.child_count != 1:
        return False
    inner = pattern.children[0]
    match inner.type:
        case "_":
            return True
        case "dotted_name":
            return inner.named_child_count == 1
        case "tuple_pattern":
            inner_patterns = [c for c in inner.named_children if c.type == "case_pattern"]
            has_comma = any(c.type == "," for c in inner.children)
            return len(inner_patterns) == 1 and not has_comma and _capture(inner_patterns[0])
    return False
