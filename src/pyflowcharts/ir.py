"""Language-neutral intermediate representation of flowcharts.

This is the contract between frontends (source parsers) and backends (renderers),
and it is exactly what the JSON output contains. It deliberately holds no layout data.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

SCHEMA_VERSION = 1

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
class FunctionChart:
    qualname: str
    name: str
    is_async: bool
    parameters: list[Parameter]
    returns: str | None
    location: SourceLocation
    nodes: list[Node]
    edges: list[Edge]


@dataclass
class Document:
    source: str
    language: str
    functions: list[FunctionChart]
    schema_version: int = SCHEMA_VERSION


@dataclass(frozen=True)
class ChartOptions:
    """Display options. They affect labels (and which assignment nodes exist), never the data."""

    show_variables: bool = False
    show_parameters: bool = True
    show_returns: bool = True
    max_label_length: int = 60
