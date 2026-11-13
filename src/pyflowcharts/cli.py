"""Command-line interface: ``pyflowcharts PATH [PATH ...] [options]``."""

from __future__ import annotations

import argparse
import sys
import unicodedata
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from pyflowcharts import __version__
from pyflowcharts.cli_options import (
    EXIT_ERROR,
    EXIT_NO_GRAPHVIZ,
    EXIT_OK,
    add_chart_options,
    chart_options,
)
from pyflowcharts.frontends.base import ParseResult
from pyflowcharts.inputs import Input, collision_error, expand
from pyflowcharts.ir import MODULE_QUALNAME
from pyflowcharts.output import Writer
from pyflowcharts.pipeline import parse_all

FORMATS = ("json", "dot", "svg", "png", "mermaid")
DEFAULT_FORMATS = ["svg", "json"]

CALLGRAPH_RESERVED = (
    "it is reserved for the call graph; rename the file, chart its parent directory instead, "
    "or pass --no-call-graph"
)


def main(argv: Sequence[str] | None = None) -> int:
    raw = sys.argv[1:] if argv is None else list(argv)
    if raw and raw[0] == "explore":
        from pyflowcharts.explorer import main as explore

        return explore(raw[1:])
    args = _parser().parse_args(raw)
    formats = list(dict.fromkeys(args.format))  # de-duplicate, keep order
    parsed = _expand_and_parse(args, formats)
    if parsed is None:
        return EXIT_ERROR
    results, ok = parsed

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


def _expand_and_parse(
    args: argparse.Namespace, formats: list[str]
) -> tuple[list[tuple[Input, ParseResult]], bool] | None:
    """Expand the paths and parse them, printing the messages on the way.

    Returns the linked results and whether everything was read, or ``None`` on an output
    name collision.
    """
    expansion = expand(args.paths, args.exclude)
    # The key is only taken when a picture will actually be written.
    pictures = not args.no_call_graph and any(fmt != "json" for fmt in formats)
    reserved = {"callgraph": CALLGRAPH_RESERVED} if pictures else {}
    if (collision := collision_error(expansion.inputs, reserved)) is not None:
        print(collision, file=sys.stderr)
        return None

    for message in expansion.warnings + expansion.errors:
        print(message, file=sys.stderr)
    parsed = parse_all(expansion.inputs, chart_options(args))
    for message in parsed.read_errors:
        print(message, file=sys.stderr)
    return parsed.results, not parsed.read_errors and not expansion.errors


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
        description=(
            "Generate a control-flow flowchart for every function in Python files. "
            "Run 'pyflowcharts explore PATH…' to browse the charts in a local web app."
        ),
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
    add_chart_options(parser)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _select(
    results: list[tuple[Input, ParseResult]], names: list[str]
) -> list[tuple[Input, ParseResult]] | None:
    """Keep only the charts named by ``--function`` (and the warnings that concern them).

    ``<module>`` names module charts. Skipped charts count as known names. Names match when
    they are Unicode-equivalent (NFKC), so a name typed as the source spells it finds the
    chart even when the frontend normalized it. Returns ``None`` after reporting unknown ones.
    """
    available: list[str] = []
    for _, result in results:
        available += [chart.qualname for chart in result.document.functions]
        if result.document.module is not None:
            available.append(MODULE_QUALNAME)
        available += [f"{w.qualname} (skipped)" for w in result.warnings if w.qualname]
    available = list(dict.fromkeys(available))
    known = {_name_key(name.removesuffix(" (skipped)")) for name in available}
    unknown = [name for name in dict.fromkeys(names) if _name_key(name) not in known]
    if unknown:
        shown = ", ".join(repr(name) for name in unknown)
        listing = ", ".join(available) or "(none)"
        print(f"error: unknown function {shown}; available: {listing}", file=sys.stderr)
        return None
    wanted = {_name_key(name) for name in names}
    selected = []
    for item, result in results:
        doc = result.document
        document = replace(
            doc,
            functions=[c for c in doc.functions if _name_key(c.qualname) in wanted],
            module=doc.module if MODULE_QUALNAME in wanted else None,
        )
        warnings = tuple(
            w for w in result.warnings if w.qualname is None or _name_key(w.qualname) in wanted
        )
        selected.append((item, replace(result, document=document, warnings=warnings)))
    return selected


def _name_key(name: str) -> str:
    return unicodedata.normalize("NFKC", name)
