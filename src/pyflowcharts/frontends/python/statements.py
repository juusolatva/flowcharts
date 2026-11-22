"""Convert tree-sitter statement nodes into model statements for the shared builder."""

from __future__ import annotations

from dataclasses import replace

from tree_sitter import Node

from pyflowcharts.cfg.model import (
    Arm,
    Block,
    Branch,
    Break,
    CallSite,
    Continue,
    Handler,
    Loop,
    Step,
    Stmt,
    Terminal,
    Try,
)
from pyflowcharts.frontends.python.calls import Resolver, call_roots
from pyflowcharts.frontends.python.discovery import Found
from pyflowcharts.frontends.python.nodes import (
    EXTRAS,
    always_true,
    calls_in_value,
    is_docstring,
    is_type_alias,
    named,
)
from pyflowcharts.frontends.python.patterns import irrefutable
from pyflowcharts.frontends.python.source import Source
from pyflowcharts.ir import ChartOptions, NodeKind

_SKIPPED = frozenset({"pass_statement", "global_statement", "nonlocal_statement"})


def convert_body(
    func: Node,
    src: Source,
    options: ChartOptions,
    resolver: Resolver | None = None,
    scope: Found | None = None,
) -> Block:
    """The function body as model statements, with a leading docstring dropped."""
    body = func.child_by_field_name("body")
    return convert_statements(body, src, options, resolver, scope)


def convert_statements(
    parent: Node | None,
    src: Source,
    options: ChartOptions,
    resolver: Resolver | None = None,
    scope: Found | None = None,
) -> Block:
    """``parent``'s statements (a function body or the module) as model statements, with a
    leading docstring dropped."""
    stmts = named(parent) if parent is not None else []
    if stmts and is_docstring(stmts[0]):
        stmts = stmts[1:]
    return _Converter(src, options, resolver, scope).stmts(stmts)


def _async_prefix(node: Node) -> str:
    """``"async "`` for an ``async def``/``for``/``with``, else ``""``."""
    return "async " if node.children and node.children[0].type == "async" else ""


def signature_label(func: Node, src: Source, options: ChartOptions) -> str:
    prefix = _async_prefix(func)
    name = _field_text(func, "name", src)
    if not options.show_parameters:
        return f"{prefix}def {name}(...)"
    label = f"{prefix}def {name}{_field_text(func, 'parameters', src)}"
    if (returns := func.child_by_field_name("return_type")) is not None:
        label += f" -> {src.source_text(returns)}"
    return label


def _field_text(node: Node, field: str, src: Source) -> str:
    child = node.child_by_field_name(field)
    return src.source_text(child) if child is not None else ""


class _Converter:
    def __init__(
        self,
        src: Source,
        options: ChartOptions,
        resolver: Resolver | None = None,
        scope: Found | None = None,
    ) -> None:
        self.src = src
        self.options = options
        self.resolver = resolver
        self.scope = scope  # the chart's function, or None for the module chart

    def _calls(self, node: Node) -> tuple[CallSite, ...]:
        return () if self.resolver is None else self.resolver.sites(call_roots(node), self.scope)

    def block(self, block: Node | None) -> Block:
        return self.stmts(named(block)) if block is not None else ()

    def stmts(self, nodes: list[Node]) -> Block:
        out: list[Stmt] = []
        for node in nodes:
            converted = self.stmt(node)
            if isinstance(converted, Try | Break | Continue):
                out.append(converted)
            elif converted is not None:
                out.append(replace(converted, calls=self._calls(node)))
        return tuple(out)

    def stmt(self, node: Node) -> Stmt | None:
        loc = self.src.location(node)
        match node.type:
            case "expression_statement":
                return self._expression(node)
            case _ if node.type in _SKIPPED:
                return None
            case "return_statement":
                values = named(node)
                value = values[0] if values else None
                if value is None or not self.options.show_returns:
                    return Terminal(NodeKind.RETURN, "return", loc)
                return Terminal(NodeKind.RETURN, f"return {self.src.source_text(value)}", loc)
            case "raise_statement":
                return Terminal(NodeKind.RAISE, self.src.source_text(node), loc)
            case "if_statement":
                return self._if(node)
            case "match_statement":
                return self._match(node)
            case "for_statement":
                prefix = _async_prefix(node)
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
                prefix = _async_prefix(node)
                # Trees with ERROR/MISSING nodes are skipped before conversion, and the
                # grammar always gives an error-free `with` a with_clause.
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
            case "type_alias_statement" if not is_type_alias(node):
                # The grammar reads `type(x).a = v` as a PEP 695 alias; it is an assignment.
                return Step(self.src.source_text(node), loc, hidden=not calls_in_value(node))
            case "break_statement":
                return Break(loc)
            case "continue_statement":
                return Continue(loc)
            case _:
                return Step(self.src.source_text(node), loc)

    def _expression(self, node: Node) -> Stmt | None:
        loc = self.src.location(node)
        children = named(node)
        inner = children[0] if len(children) == 1 else None
        if inner is not None:
            match inner.type:
                case "ellipsis":
                    return None
                case "assignment" | "augmented_assignment":
                    hidden = not calls_in_value(inner)
                    return Step(self.src.source_text(node), loc, hidden=hidden)
        return Step(self.src.source_text(node), loc)

    def _if(self, node: Node) -> Branch:
        alternatives = [c for c in node.children if c.type in ("elif_clause", "else_clause")]
        return self._if_chain(node, alternatives)

    def _if_chain(self, clause: Node, rest: list[Node]) -> Branch:
        """``clause`` (the ``if_statement`` or an ``elif_clause``) as a branch. The clauses in
        ``rest`` follow it: an ``else`` is its False arm, and an ``elif`` is a nested branch
        there, which takes the clauses after it."""
        arms = [Arm("True", self.block(clause.child_by_field_name("consequence")))]
        default: str | None = "False"
        if rest:
            default = None
            following = rest[0]
            if following.type == "else_clause":
                arms.append(Arm("False", self.block(following.child_by_field_name("body"))))
            else:
                arms.append(Arm("False", (self._if_chain(following, rest[1:]),)))
        # stmts() gives the if_statement its calls; a nested elif is not a statement of its own.
        calls = self._calls(clause) if clause.type == "elif_clause" else ()
        return Branch(
            f"if {self._text(clause, 'condition')}",
            self.src.location(clause),
            tuple(arms),
            default,
            calls=calls,
        )

    def _match(self, node: Node) -> Branch:
        body = node.child_by_field_name("body")
        cases = [
            c for c in (body.named_children if body is not None else []) if c.type == "case_clause"
        ]
        arms = []
        for case in cases:
            label = "case " + self._list_text(_between(case, "case", ("guard", ":")))
            if (guard := case.child_by_field_name("guard")) is not None:
                label += f" {self.src.source_text(guard)}"
            arms.append(Arm(label, self.block(case.child_by_field_name("consequence"))))
        default = None if cases and irrefutable(cases[-1]) else "no match"
        subject = self._list_text(_between(node, "match", (":",)))
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
                    # Error-free trees only (see `with_statement`): a finally has a block.
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
            label += " " + self._list_text(rest)  # PEP 758: `except A, B:`
        block = next((c for c in clause.children if c.type == "block"), None)
        return Handler(label, self.src.location(clause), self.block(block), self._calls(clause))

    def _list_text(self, nodes: list[Node]) -> str:
        """Source text of a comma-separated list, keeping a trailing comma (``x,``)."""
        parts: list[str] = []
        for node in nodes:
            if node.type == ",":
                parts[-1] += ","
            elif node.type not in EXTRAS:
                parts.append(self.src.source_text(node))
        return " ".join(parts)

    def _body(self, node: Node) -> Block:
        return self.block(node.child_by_field_name("body"))

    def _else(self, node: Node) -> Block:
        for child in node.children:
            if child.type == "else_clause":
                return self.block(child.child_by_field_name("body"))
        return ()

    def _text(self, node: Node, field: str) -> str:
        return _field_text(node, field, self.src)


def _between(node: Node, after: str, until: tuple[str, ...]) -> list[Node]:
    """The children after the ``after`` keyword, up to the first child whose type (or field
    name) is in ``until``."""
    out: list[Node] = []
    started = False
    for i, child in enumerate(node.children):
        if not started:
            started = child.type == after
            continue
        if child.type in until or (node.field_name_for_child(i) or "") in until:
            break
        out.append(child)
    return out
