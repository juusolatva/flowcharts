"""Language-neutral intermediate representation of flowcharts.

This is the contract between frontends (source parsers) and backends (renderers),
and it is exactly what the JSON output contains. It deliberately holds no layout data.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

SCHEMA_VERSION = 2

MODULE_QUALNAME = "<module>"  # qualname of a file's module-level chart

EXCEPTION_LABEL = "exception"  # edge label of every exception path; backends draw it dashed


class NodeKind(StrEnum):
    START = "start"
    END = "end"
    PROCESS = "process"
    DECISION = "decision"
    LOOP = "loop"
    RETURN = "return"
    RAISE = "raise"


class ParamKind(StrEnum):
    POSITIONAL_ONLY = "positional_only"
    POSITIONAL_OR_KEYWORD = "positional_or_keyword"
    VAR_POSITIONAL = "var_positional"
    KEYWORD_ONLY = "keyword_only"
    VAR_KEYWORD = "var_keyword"


@dataclass(frozen=True)
class SourceLocation:
    line: int
    column: int
    end_line: int
    end_column: int


@dataclass(frozen=True)
class Node:
    id: str
    kind: NodeKind
    label: str
    location: SourceLocation | None


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    label: str | None = None


@dataclass(frozen=True)
class Parameter:
    name: str
    annotation: str | None
    default: str | None
    kind: ParamKind


@dataclass
class Chart:
    """One flowchart: a function's or, with qualname ``MODULE_QUALNAME``, a module's."""

    qualname: str
    location: SourceLocation
    nodes: list[Node]
    edges: list[Edge]


@dataclass
class FunctionChart(Chart):
    name: str
    is_async: bool
    parameters: list[Parameter]
    returns: str | None


@dataclass
class Document:
    source: str
    language: str
    functions: list[FunctionChart]
    module: Chart | None = None
    schema_version: int = SCHEMA_VERSION


@dataclass(frozen=True)
class ChartOptions:
    """Display options. They affect labels, which assignment nodes exist and whether a module
    chart is built, never the data inside a chart."""

    show_variables: bool = False
    show_parameters: bool = True
    show_returns: bool = True
    max_label_length: int = 60
    show_module: bool = True
