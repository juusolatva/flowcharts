"""Find every function in a tree-sitter tree and read its signature."""

from __future__ import annotations

from dataclasses import dataclass

from tree_sitter import Node

from pyflowcharts.frontends.python.source import Source, identifier
from pyflowcharts.ir import Parameter, ParamKind


@dataclass(frozen=True)
class Found:
    node: Node
    qualname: str
    name: str
    is_async: bool
    enclosing: Found | None  # the nearest enclosing function, None for an outermost one


def find_functions(root: Node) -> list[Found]:
    """Every ``function_definition`` in source order, including those inside ``ERROR``
    nodes. Qualnames come from the class/function ancestors tree-sitter recognises."""
    finder = _Finder()
    finder.walk(root, "", None)
    return finder.found


class _Finder:
    def __init__(self) -> None:
        self.found: list[Found] = []
        self._seen: set[str] = set()

    def walk(self, node: Node, prefix: str, enclosing: Found | None) -> None:
        for child in node.children:
            match child.type:
                case "function_definition":
                    name = _name(child)
                    qualname = self._unique(prefix + name, child.start_point.row + 1)
                    is_async = child.children[0].type == "async"
                    found = Found(child, qualname, name, is_async, enclosing)
                    self.found.append(found)
                    self.walk(child, qualname + ".", found)
                case "class_definition":
                    self.walk(child, prefix + _name(child) + ".", enclosing)
                case _:
                    self.walk(child, prefix, enclosing)

    def _unique(self, qualname: str, line: int) -> str:
        if qualname in self._seen:
            qualname = f"{qualname}@L{line}"
        self._seen.add(qualname)
        return qualname


def _name(node: Node) -> str:
    name = node.child_by_field_name("name")
    return identifier(name) if name is not None else ""


def parameters(func: Node, src: Source) -> list[Parameter]:
    params = func.child_by_field_name("parameters")
    if params is None:
        return []
    out: list[Parameter] = []
    kind = ParamKind.POSITIONAL_OR_KEYWORD
    for node in params.named_children:
        match node.type:
            case "positional_separator":
                out = [
                    Parameter(p.name, p.annotation, p.default, ParamKind.POSITIONAL_ONLY)
                    for p in out
                ]
            case "keyword_separator":
                kind = ParamKind.KEYWORD_ONLY
            case "list_splat_pattern":
                out.append(Parameter(_target(node), None, None, ParamKind.VAR_POSITIONAL))
                kind = ParamKind.KEYWORD_ONLY
            case "dictionary_splat_pattern":
                out.append(Parameter(_target(node), None, None, ParamKind.VAR_KEYWORD))
            case "identifier":
                out.append(Parameter(_target(node), None, None, kind))
            case "typed_parameter" | "default_parameter" | "typed_default_parameter":
                out.append(_parameter(node, kind, src))
                if node.children[0].type == "list_splat_pattern":
                    kind = ParamKind.KEYWORD_ONLY
    return out


def _parameter(node: Node, kind: ParamKind, src: Source) -> Parameter:
    target = node.children[0]
    match target.type:
        case "list_splat_pattern":
            kind = ParamKind.VAR_POSITIONAL
        case "dictionary_splat_pattern":
            kind = ParamKind.VAR_KEYWORD
    annotation = node.child_by_field_name("type")
    default = node.child_by_field_name("value")
    return Parameter(
        _target(target),
        src.source_text(annotation) if annotation is not None else None,
        src.source_text(default) if default is not None else None,
        kind,
    )


def _target(node: Node) -> str:
    """The parameter name: the identifier itself, or the one inside ``*``/``**``."""
    if node.type == "identifier":
        return identifier(node)
    return _target(node.named_children[0])


def returns(func: Node, src: Source) -> str | None:
    node = func.child_by_field_name("return_type")
    return src.source_text(node) if node is not None else None
