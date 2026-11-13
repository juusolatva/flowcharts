"""Module-level code: decide whether a file's top level does work, and chart it if so."""

from __future__ import annotations

from pathlib import PurePath

from tree_sitter import Node

from pyflowcharts.cfg.builder import build_chart
from pyflowcharts.frontends.python.source import Source
from pyflowcharts.frontends.python.statements import convert_statements, is_docstring, named
from pyflowcharts.ir import MODULE_QUALNAME, Chart, ChartOptions, SourceLocation

UNSUPPORTED = "unsupported syntax in module code; module chart skipped"
STRAY = "syntax error in module code; module chart skipped"

_DECLARATIONS = frozenset(
    {
        "import_statement",
        "import_from_statement",
        "future_import_statement",
        "function_definition",
        "decorated_definition",
        "class_definition",
        "type_alias_statement",
        "pass_statement",
        "global_statement",
    }
)
_QUIET_EXPRESSIONS = frozenset({"assignment", "augmented_assignment", "ellipsis"})


def does_work(root: Node) -> bool:
    """Whether the top level has a statement other than a docstring, imports, definitions,
    assignments, ``pass``, ``...`` or ``global`` (library modules get no module chart)."""
    stmts = named(root)
    if stmts and is_docstring(stmts[0]):
        stmts = stmts[1:]
    return not all(_declares(stmt) for stmt in stmts)


def _declares(stmt: Node) -> bool:
    if stmt.type in _DECLARATIONS:
        return True
    children = named(stmt)
    return (
        stmt.type == "expression_statement"
        and len(children) == 1
        and children[0].type in _QUIET_EXPRESSIONS
    )


def module_chart(root: Node, src: Source, path: str, options: ChartOptions) -> Chart:
    """The module's top-level statements as a chart. Raises ``StrayLoopTransfer`` for a
    top-level ``break``/``continue``."""
    location = _location(root, src)
    nodes, edges, calls = build_chart(
        MODULE_QUALNAME,
        f"module {PurePath(path).stem}",
        location,
        convert_statements(root, src, options),
        options,
    )
    return Chart(qualname=MODULE_QUALNAME, location=location, nodes=nodes, edges=edges, calls=calls)


def _location(root: Node, src: Source) -> SourceLocation:
    """From the first statement (leading comments such as a shebang excluded) to the last
    token."""
    end = src.location(root)
    first = named(root)[0]
    return SourceLocation(
        line=first.start_point.row + 1,
        column=first.start_point.column,
        end_line=end.end_line,
        end_column=end.end_column,
    )
