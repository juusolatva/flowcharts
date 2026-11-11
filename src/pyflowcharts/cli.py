"""Command-line interface: ``pyflowcharts FILE [FILE ...] [options]``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import graphviz

from pyflowcharts import __version__
from pyflowcharts.backends.dot import render, to_dot
from pyflowcharts.backends.mermaid import to_mermaid
from pyflowcharts.frontends import SourceError, frontend_for_path
from pyflowcharts.ir import ChartOptions, Document
from pyflowcharts.serialize import to_json

FORMATS = ("json", "dot", "svg", "png", "mermaid")
DEFAULT_FORMATS = ["svg", "json"]
EXTENSIONS = {"dot": "dot", "svg": "svg", "png": "png", "mermaid": "mmd"}

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_GRAPHVIZ = 2

GRAPHVIZ_MISSING = (
    "error: Graphviz 'dot' executable not found; install Graphviz "
    "(e.g. 'sudo apt install graphviz') or use --format json dot mermaid"
)


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
    documents: list[tuple[Path, Document]] = []
    for path in files:
        try:
            documents.append((path, _parse_file(path, options)))
        except SourceError as err:
            print(err, file=sys.stderr)
            status = EXIT_ERROR

    if args.function:
        available = [chart.qualname for _, doc in documents for chart in doc.functions]
        unknown = [name for name in dict.fromkeys(args.function) if name not in available]
        if unknown:
            names = ", ".join(repr(name) for name in unknown)
            listing = ", ".join(available) or "(none)"
            print(f"error: unknown function {names}; available: {listing}", file=sys.stderr)
            return EXIT_ERROR
        wanted = set(args.function)
        for _, doc in documents:
            doc.functions = [chart for chart in doc.functions if chart.qualname in wanted]

    writer = _Writer(args.output, formats)
    for path, doc in documents:
        if not doc.functions:
            print(f"warning: {path}: no functions found", file=sys.stderr)
        writer.write(doc, path.stem)

    if writer.graphviz_missing and status == EXIT_OK:
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


def _parse_file(path: Path, options: ChartOptions) -> Document:
    frontend = frontend_for_path(path)
    try:
        source = path.read_bytes()
    except FileNotFoundError:
        raise SourceError(str(path), "no such file") from None
    except OSError as err:
        raise SourceError(str(path), err.strerror or str(err)) from None
    return frontend.parse(source, str(path), options)


class _Writer:
    """Writes the selected formats; reports a missing Graphviz once and skips images after."""

    def __init__(self, outdir: Path, formats: list[str]) -> None:
        self.outdir = outdir
        self.formats = formats
        self.graphviz_missing = False

    def write(self, doc: Document, stem: str) -> None:
        self.outdir.mkdir(parents=True, exist_ok=True)
        if "json" in self.formats:
            (self.outdir / f"{stem}.json").write_text(to_json(doc), encoding="utf-8")
        per_function = [fmt for fmt in self.formats if fmt != "json"]
        if not per_function or not doc.functions:
            return
        chart_dir = self.outdir / stem
        chart_dir.mkdir(exist_ok=True)
        for chart in doc.functions:
            for fmt in per_function:
                target = chart_dir / f"{chart.qualname}.{EXTENSIONS[fmt]}"
                match fmt:
                    case "dot":
                        target.write_text(to_dot(chart), encoding="utf-8")
                    case "mermaid":
                        target.write_text(to_mermaid(chart), encoding="utf-8")
                    case "svg" | "png" if not self.graphviz_missing:
                        try:
                            target.write_bytes(render(chart, fmt))
                        except graphviz.ExecutableNotFound:
                            print(GRAPHVIZ_MISSING, file=sys.stderr)
                            self.graphviz_missing = True
