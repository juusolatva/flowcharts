"""Command-line interface: ``pyflowcharts PATH [PATH ...] [options]``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from pyflowcharts import __version__
from pyflowcharts.frontends.base import ParseResult
from pyflowcharts.inputs import Input, collision_error, expand
from pyflowcharts.ir import MODULE_QUALNAME, ChartOptions
from pyflowcharts.output import Writer
from pyflowcharts.pipeline import parse_all

FORMATS = ("json", "dot", "svg", "png", "mermaid")
DEFAULT_FORMATS = ["svg", "json"]

CALLGRAPH_RESERVED = (
    "it is reserved for the call graph; rename the file, chart its parent directory instead, "
    "or pass --no-call-graph"
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_GRAPHVIZ = 2


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    formats = list(dict.fromkeys(args.format))  # de-duplicate, keep order
    expansion = expand(args.paths, args.exclude)
    # The key is only taken when a picture will actually be written.
    pictures = not args.no_call_graph and any(fmt != "json" for fmt in formats)
    reserved = {"callgraph": CALLGRAPH_RESERVED} if pictures else {}
    if (collision := collision_error(expansion.inputs, reserved)) is not None:
        print(collision, file=sys.stderr)
        return EXIT_ERROR

    for message in expansion.warnings + expansion.errors:
        print(message, file=sys.stderr)
    parsed = parse_all(expansion.inputs, _options(args))
    for message in parsed.read_errors:
        print(message, file=sys.stderr)
    results = parsed.results
    ok = not parsed.read_errors and not expansion.errors

    # Decided on the full result, so a file that only lacks the requested functions is quiet.
    empty = {item.path for item, result in results if item.explicit and _nothing_to_chart(result)}
    if args.function:
        results = _select(results, args.function)
        if results is None:
            return EXIT_ERROR
    if not _report(results, empty):
        ok = False

    writer = Writer(args.output, formats)
    for item, result in results:
        writer.write(result.document, item.key)
    if not args.no_call_graph:
        writer.write_callgraph([result.document for _, result in results])

    if writer.write_failed or not ok:
        return EXIT_ERROR
    return EXIT_NO_GRAPHVIZ if writer.graphviz_missing else EXIT_OK


def _options(args: argparse.Namespace) -> ChartOptions:
    return ChartOptions(
        show_variables=args.variables,
        show_parameters=not args.no_parameters,
        show_returns=not args.no_returns,
        max_label_length=args.max_label,
        show_module=not args.no_module,
    )


def _report(results: list[tuple[Input, ParseResult]], empty: set[Path]) -> bool:
    """Print each file's warnings and the "nothing to chart" notes; ``False`` if any file
    had warnings."""
    ok = True
    for item, result in results:
        for warning in result.warnings:
            print(warning, file=sys.stderr)
            ok = False
        if item.path in empty:
            print(f"warning: {item.path}: nothing to chart", file=sys.stderr)
    return ok


def _nothing_to_chart(result: ParseResult) -> bool:
    doc = result.document
    return not doc.functions and doc.module is None and not result.warnings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyflowcharts",
        description="Generate a control-flow flowchart for every function in Python files.",
        epilog=(
            "Put input paths before options that take several values (-f, --function, --exclude)."
        ),
    )
    parser.add_argument(
        "paths", nargs="+", type=Path, metavar="PATH", help="source files or directories"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("flowcharts"),
        metavar="OUTDIR",
        help="output directory (default: flowcharts)",
    )
    parser.add_argument(
        "-f",
        "--format",
        nargs="+",
        choices=FORMATS,
        default=DEFAULT_FORMATS,
        metavar="FORMAT",
        help=f"one or more of: {', '.join(FORMATS)} (default: svg json)",
    )
    parser.add_argument("--variables", action="store_true", help="show plain variable assignments")
    parser.add_argument(
        "--no-parameters", action="store_true", help="hide parameters in the start node"
    )
    parser.add_argument(
        "--no-returns", action="store_true", help="hide returned values in return nodes"
    )
    parser.add_argument("--no-module", action="store_true", help="never chart module-level code")
    parser.add_argument(
        "--no-call-graph", action="store_true", help="do not write the run's call graph picture"
    )
    parser.add_argument(
        "--function",
        nargs="+",
        action="extend",
        metavar="QUALNAME",
        help="only chart these functions (e.g. 'load' or 'Inventory.find'); repeatable",
    )
    parser.add_argument(
        "--exclude",
        nargs="+",
        action="extend",
        default=[],
        type=_exclude_pattern,
        metavar="GLOB",
        help="skip matching files and directories when walking a directory; a pattern "
        "without '/' matches names, one with '/' the relative path, and a trailing '/' "
        "matches directories only; repeatable",
    )
    parser.add_argument(
        "--max-label",
        type=_positive_int,
        default=ChartOptions().max_label_length,
        metavar="N",
        help="truncate node labels to N characters (default: 60)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _exclude_pattern(text: str) -> str:
    if text.rstrip("/") == "":
        raise argparse.ArgumentTypeError(f"must name a file or directory, got {text!r}")
    return text


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {text!r}")
    return value


def _select(
    results: list[tuple[Input, ParseResult]], names: list[str]
) -> list[tuple[Input, ParseResult]] | None:
    """Keep only the charts named by ``--function`` (and the warnings that concern them).

    ``<module>`` names module charts. Skipped charts count as known names. Returns ``None``
    after reporting unknown ones.
    """
    available: list[str] = []
    for _, result in results:
        available += [chart.qualname for chart in result.document.functions]
        if result.document.module is not None:
            available.append(MODULE_QUALNAME)
        available += [f"{w.qualname} (skipped)" for w in result.warnings if w.qualname]
    available = list(dict.fromkeys(available))
    known = {name.removesuffix(" (skipped)") for name in available}
    unknown = [name for name in dict.fromkeys(names) if name not in known]
    if unknown:
        shown = ", ".join(repr(name) for name in unknown)
        listing = ", ".join(available) or "(none)"
        print(f"error: unknown function {shown}; available: {listing}", file=sys.stderr)
        return None
    wanted = set(names)
    selected = []
    for item, result in results:
        doc = result.document
        document = replace(
            doc,
            functions=[c for c in doc.functions if c.qualname in wanted],
            module=doc.module if MODULE_QUALNAME in wanted else None,
        )
        warnings = tuple(w for w in result.warnings if w.qualname is None or w.qualname in wanted)
        selected.append((item, replace(result, document=document, warnings=warnings)))
    return selected
