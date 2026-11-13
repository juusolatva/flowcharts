"""Find the calls in Python code and the charts they may reach (static, best-effort)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from tree_sitter import Node

from pyflowcharts.cfg.model import CallSite
from pyflowcharts.frontends.python.discovery import Found
from pyflowcharts.frontends.python.source import Source


@dataclass(frozen=True)
class ModuleInfo:
    """A file's dotted module name (``""`` when it has none) and the package that relative
    imports start from."""

    name: str
    package: tuple[str, ...]


def module_info(key: PurePosixPath) -> ModuleInfo:
    """``pkg/io/load`` → ``pkg.io.load`` in package ``pkg.io``; ``pkg/__init__`` → ``pkg``
    in package ``pkg``; a bare ``__init__`` has no module name."""
    package = key.parts[:-1]
    if key.name == "__init__":
        return ModuleInfo(".".join(package), package)
    return ModuleInfo(".".join(key.parts), package)


def call_roots(stmt: Node) -> list[Node]:
    """The subtrees whose calls the statement's node owns (the spec's ownership table)."""
    match stmt.type:
        case "if_statement" | "elif_clause" | "while_statement":
            return _fields(stmt, "condition")
        case "match_statement":
            body = stmt.child_by_field_name("body")
            cases = body.named_children if body is not None else []
            guards = [g for c in cases if (g := c.child_by_field_name("guard")) is not None]
            return stmt.children_by_field_name("subject") + guards
        case "for_statement":
            return _fields(stmt, "left", "right")
        case "with_statement":
            return [c for c in stmt.children if c.type == "with_clause"]
        case "except_clause" | "except_group_clause":
            return [c for c in stmt.children if c.type != "block"]
        case "decorated_definition":
            decorators = [c for c in stmt.children if c.type == "decorator"]
            definition = stmt.child_by_field_name("definition")
            return decorators + (call_roots(definition) if definition is not None else [])
        case "function_definition":
            return _fields(stmt, "type_parameters", "parameters", "return_type")
    return [stmt]


def _fields(node: Node, *names: str) -> list[Node]:
    return [c for name in names if (c := node.child_by_field_name(name)) is not None]


class Resolver:
    """Finds a file's call sites and their candidate targets."""

    def __init__(self, root: Node, functions: list[Found], info: ModuleInfo, src: Source) -> None:
        self.root = root
        self.functions = functions
        self.info = info
        self.src = src

    def sites(self, roots: Sequence[Node], scope: Found | None) -> tuple[CallSite, ...]:
        """Every call in ``roots``, in pre-order, skipping function bodies. ``scope`` is the
        owning chart's function (``None`` for the module chart)."""
        out: list[CallSite] = []
        for root in roots:
            for call in _calls(root):
                callee = call.child_by_field_name("function")
                if callee is not None:
                    out.append(CallSite(self.src.source_text(callee), ()))
        return tuple(out)


def _calls(node: Node) -> Iterator[Node]:
    if node.type == "call":
        yield node
    skip_body = node.type == "function_definition"
    for i, child in enumerate(node.children):
        if skip_body and node.field_name_for_child(i) == "body":
            continue
        yield from _calls(child)
