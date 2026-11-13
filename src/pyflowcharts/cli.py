"""Command-line interface: ``pyflowcharts FILE [FILE ...] [options]``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pyflowcharts import __version__
from pyflowcharts.frontends import SourceError, frontend_for_path
from pyflowcharts.frontends.base import ParseResult
from pyflowcharts.ir import ChartOptions, Document
from pyflowcharts.output import Writer

FORMATS = ("json", "dot", "svg", "png", "mermaid")
DEFAULT_FORMATS = ["svg", "json"]

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_GRAPHVIZ = 2


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    formats = list(dict.fromkeys(args.format))  # de-duplicate, keep order
    options = ChartOptions(
        show_variables=args.variables,
        show_parameters=not args.no_parameters,
        show_returns=not args.no_returns,
        max_label_length=args.max_label,
    )
    files = _unique_paths(args.files)
    if (collision := _stem_collision(files)) is not None:
        first, second = collision
        print(
            f"error: output name collision: {first} and {second} both map to '{first.stem}'; "
            "run them separately with different --output directories",
            file=sys.stderr,
        )
        return EXIT_ERROR

    status = EXIT_OK
    results: list[tuple[Path, ParseResult]] = []
    for path in files:
        try:
            results.append((path, _parse_file(path, options)))
        except SourceError as err:
            print(err, file=sys.stderr)
            status = EXIT_ERROR

    if args.function:
        results = _select(results, args.function)
        if results is None:
            return EXIT_ERROR

    documents: list[tuple[Path, Document]] = []
    for path, result in results:
        for warning in result.warnings:
            print(warning, file=sys.stderr)
            status = EXIT_ERROR
        skipped_any = any(w.qualname is not None for w in result.warnings)
        if not result.document.functions and not skipped_any:
            print(f"warning: {path}: no functions found", file=sys.stderr)
        documents.append((path, result.document))

    writer = Writer(args.output, formats)
    for path, doc in documents:
        writer.write(doc, path.stem)

    if writer.write_failed:
        status = EXIT_ERROR
    elif writer.graphviz_missing and status == EXIT_OK:
        status = EXIT_NO_GRAPHVIZ
    return status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyflowcharts",
        description="Generate a control-flow flowchart for every function in Python files.",
        epilog="Put input files before options that take several values (-f, --function).",
    )
    parser.add_argument("files", nargs="+", type=Path, metavar="FILE", help="source files")
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
    parser.add_argument(
        "--function",
        nargs="+",
        action="extend",
        metavar="QUALNAME",
        help="only chart these functions (e.g. 'load' or 'Inventory.find'); repeatable",
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


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {text!r}")
    return value


def _unique_paths(paths: list[Path]) -> list[Path]:
    """Drop repeated mentions of the same file, keeping the first spelling."""
    seen: set[Path] = set()
    unique = []
    for path in paths:
        key = path.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _stem_collision(paths: list[Path]) -> tuple[Path, Path] | None:
    by_stem: dict[str, Path] = {}
    for path in paths:
        if path.stem in by_stem:
            return by_stem[path.stem], path
        by_stem[path.stem] = path
    return None


def _select(
    results: list[tuple[Path, ParseResult]], names: list[str]
) -> list[tuple[Path, ParseResult]] | None:
    """Keep only the charts named by ``--function`` (and the warnings that concern them).

    Skipped functions count as known names. Returns ``None`` after reporting unknown ones.
    """
    available: list[str] = []
    for _, result in results:
        available += [chart.qualname for chart in result.document.functions]
        available += [f"{w.qualname} (skipped)" for w in result.warnings if w.qualname]
    known = {name.removesuffix(" (skipped)") for name in available}
    unknown = [name for name in dict.fromkeys(names) if name not in known]
    if unknown:
        shown = ", ".join(repr(name) for name in unknown)
        listing = ", ".join(available) or "(none)"
        print(f"error: unknown function {shown}; available: {listing}", file=sys.stderr)
        return None
    wanted = set(names)
    selected = []
    for path, result in results:
        functions = [c for c in result.document.functions if c.qualname in wanted]
        warnings = tuple(w for w in result.warnings if w.qualname is None or w.qualname in wanted)
        document = Document(result.document.source, result.document.language, functions)
        selected.append((path, ParseResult(document, warnings)))
    return selected


def _parse_file(path: Path, options: ChartOptions) -> ParseResult:
    frontend = frontend_for_path(path)
    try:
        source = path.read_bytes()
    except FileNotFoundError:
        raise SourceError(str(path), "no such file") from None
    except OSError as err:
        raise SourceError(str(path), err.strerror or str(err)) from None
    return frontend.parse(source, str(path), options)
