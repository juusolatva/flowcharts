"""Language-neutral intermediate representation of flowcharts.

This is the contract between frontends (source parsers) and backends (renderers),
and it is exactly what the JSON output contains. It deliberately holds no layout data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

SCHEMA_VERSION = 3

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


@dataclass(frozen=True)
class CallRef:
    """A chart that a call may reach: its dotted module name and qualname in that module."""

    module: str
    qualname: str


@dataclass(frozen=True)
class Call:
    """A call written in a chart node. ``candidates`` lists where it may go, most likely
    first; ``target`` is the first candidate charted in the run, set by the linker."""

    node: str
    text: str
    candidates: list[CallRef]
    target: CallRef | None


@dataclass
class Chart:
    """One flowchart: a function's or, with qualname ``MODULE_QUALNAME``, a module's."""

    qualname: str
    location: SourceLocation
    nodes: list[Node]
    edges: list[Edge]
    calls: list[Call] = field(default_factory=list, kw_only=True)


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
    module_name: str = field(default="", kw_only=True)  # keyword-only: positional order unchanged
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
