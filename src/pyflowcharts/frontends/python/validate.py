"""Decide which functions are valid Python, using ``ast.parse`` as the oracle.

Tree-sitter accepts some invalid Python without error nodes (empty bodies, ``try`` without
handlers, inconsistent indentation), so each function is checked with Python's own parser
on a slice of the file that keeps its line numbers.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from tree_sitter import Node

from pyflowcharts.frontends.base import Diagnostic
from pyflowcharts.frontends.python.discovery import Found
from pyflowcharts.frontends.python.source import Source

OUTSIDE = "syntax error outside functions; nearby code may be missing"
_HEADER = b"if 1:\n"


@dataclass(frozen=True)
class Validation:
    skipped: dict[str, Diagnostic]  # by qualname, in source order
    outside: Diagnostic | None


def validate(src: Source, functions: list[Found], path: str) -> Validation:
    file_ok = _parses(src.data) is None
    outside = None
    if not file_ok:
        skeleton = _stub_all(src.data, [f for f in functions if f.enclosing is None])
        if (line := _parses(skeleton)) is not None:
            outside = Diagnostic(path, line, OUTSIDE, None)
    skipped: dict[str, Diagnostic] = {}
    for func in functions:
        ast_line = None if file_ok else _check_function(src.data, func, functions)
        ts_line = _first_error_line(func.node)
        if ast_line is None and ts_line is None:
            continue
        message = f"syntax error in '{func.qualname}'; function skipped"
        line = ast_line if ast_line is not None else ts_line
        skipped[func.qualname] = Diagnostic(path, line, message, func.qualname)
    if not file_ok and outside is None and not skipped:
        outside = Diagnostic(path, _parses(src.data), OUTSIDE, None)
    return Validation(skipped, outside)


def _parses(data: bytes) -> int | None:
    """``None`` if the source parses, else the line of the syntax error."""
    try:
        ast.parse(data.decode())
    except SyntaxError as e:
        return e.lineno or 1
    return None


def _check_function(data: bytes, func: Found, functions: list[Found]) -> int | None:
    """The mapped, clamped error line of the function's own source, or ``None``."""
    nested = [f for f in functions if f.enclosing is func]
    stubbed = _stub_all(data, nested)
    first, last = func.node.start_point.row, func.node.end_point.row
    lines = stubbed.split(b"\n")[first : last + 1]
    header = _HEADER if func.node.start_point.column > 0 else b""
    line = _parses(header + b"\n".join(lines))
    if line is None:
        return None
    line = line - (1 if header else 0) + first
    return min(max(line, first + 1), last + 1)


def _stub_all(data: bytes, functions: list[Found]) -> bytes:
    """Replace each function's signature and body (everything after its name) with
    ``(): pass`` and blanks. Newlines are kept, so line numbers are unchanged."""
    for func in sorted(functions, key=lambda f: f.node.start_byte, reverse=True):
        name = func.node.child_by_field_name("name")
        if name is None:
            continue
        region = re.sub(rb"[^\n]", b" ", data[name.end_byte : func.node.end_byte])
        data = data[: name.end_byte] + b"(): pass" + region + data[func.node.end_byte :]
    return data


def _first_error_line(node: Node) -> int | None:
    """Line of the first ``ERROR``/``MISSING`` node in the function's own subtree (nested
    functions excluded), or ``None``."""
    if not node.has_error:
        return None
    for child in node.children:
        if child.is_error or child.is_missing:
            return child.start_point.row + 1
        if child.type == "function_definition":
            continue
        if (line := _first_error_line(child)) is not None:
            return line
    return None
