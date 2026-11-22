"""Decide which functions are valid Python, using ``ast.parse`` as the oracle.

Tree-sitter accepts some invalid Python without error nodes (empty bodies, ``try`` without
handlers, inconsistent indentation), so each function is checked with Python's own parser
on a slice of the file that keeps its line numbers.
"""

from __future__ import annotations

import ast
import warnings
from dataclasses import dataclass

from tree_sitter import Node

from pyflowcharts.frontends.base import Diagnostic
from pyflowcharts.frontends.python.discovery import Found
from pyflowcharts.frontends.python.source import Source

OUTSIDE = "syntax error outside functions; nearby code may be missing"
_HEADER = b"if 1:\n"
# Every byte but a newline becomes a space, so blanked code keeps its line numbers.
_BLANK = bytes(byte if byte == ord("\n") else ord(" ") for byte in range(256))


@dataclass(frozen=True)
class Validation:
    skipped: dict[str, Diagnostic]  # by qualname, in source order
    outside: Diagnostic | None


def validate(src: Source, functions: list[Found], path: str) -> Validation:
    file_ok = _parses(src.data) is None
    recovery = None if file_ok else _Recovery(src, functions)
    outside = None
    if recovery is not None and (line := recovery.skeleton_error()) is not None:
        outside = Diagnostic(path, line, OUTSIDE, None)
    skipped: dict[str, Diagnostic] = {}
    for func in functions:
        ast_line = None if recovery is None else recovery.error_line(func)
        ts_line = first_error_line(func.node)
        if ast_line is None and ts_line is None:
            continue
        # Code the interpreter accepts but the grammar does not (newer syntax) is not an error.
        problem = "syntax error" if ast_line is not None else "unsupported syntax"
        message = f"{problem} in '{func.qualname}'; function skipped"
        line = ast_line if ast_line is not None else ts_line
        skipped[func.qualname] = Diagnostic(path, line, message, func.qualname)
    if not file_ok and outside is None and not skipped:
        outside = Diagnostic(path, _parses(src.data), OUTSIDE, None)
    return Validation(skipped, outside)


class _Recovery:
    """Checks the functions of a file that does not parse, each on its own lines with the
    functions directly inside it stubbed, so the whole check stays linear in file size."""

    def __init__(self, src: Source, functions: list[Found]) -> None:
        self.src = src
        self.top_level = [f for f in functions if f.enclosing is None]
        self.children: dict[int, list[Found]] = {}  # by id() of the enclosing Found
        for func in functions:
            if func.enclosing is not None:
                self.children.setdefault(id(func.enclosing), []).append(func)
        self.starts = [0]  # byte offset where each line starts
        for text in src.lines[:-1]:
            self.starts.append(self.starts[-1] + len(text) + 1)

    def skeleton_error(self) -> int | None:
        """The error line of the code outside every function, or ``None``."""
        return _parses(_stub(self.src.data, self.top_level))

    def error_line(self, func: Found) -> int | None:
        """The mapped, clamped error line of the function's own source, or ``None``."""
        first, last = func.node.start_point.row, func.node.end_point.row
        base = self.starts[first]
        segment = self.src.data[base : self.starts[last] + len(self.src.lines[last])]
        header = _HEADER if func.node.start_point.column > 0 else b""
        nested = self.children.get(id(func), [])
        line = _parses(header + _stub(segment, nested, base))
        if line is None:
            return None
        line = line - (1 if header else 0) + first
        return min(max(line, first + 1), last + 1)


def _parses(data: bytes) -> int | None:
    """``None`` if the source parses, else the line of the syntax error."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # SyntaxWarnings about the user's code are not ours
            ast.parse(data.decode())
    except SyntaxError as e:
        return e.lineno or 1
    return None


def _stub(data: bytes, functions: list[Found], base: int = 0) -> bytes:
    """Replace each function's signature and body (everything after its name) with
    ``(): pass`` and blanks. Newlines are kept, so line numbers are unchanged. ``data``
    starts at byte ``base`` of the file; the functions must not overlap (siblings)."""
    pieces: list[bytes] = []
    position = 0
    for func in sorted(functions, key=lambda f: f.node.start_byte):
        name = func.node.child_by_field_name("name")
        if name is None:
            continue
        start, end = name.end_byte - base, func.node.end_byte - base
        pieces += [data[position:start], b"(): pass", data[start:end].translate(_BLANK)]
        position = end
    pieces.append(data[position:])
    return b"".join(pieces)


def first_error_line(node: Node) -> int | None:
    """Line of the first ``ERROR``/``MISSING`` node in ``node``'s subtree, with function
    definitions below it excluded (for a function: its own code; for the module root: the
    code outside every function), or ``None``."""
    if not node.has_error:
        return None
    for child in node.children:
        if child.is_error or child.is_missing:
            return child.start_point.row + 1
        if child.type == "function_definition":
            continue
        if (line := first_error_line(child)) is not None:
            return line
    return None
