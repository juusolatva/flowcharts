"""Chart options shared by ``pyflowcharts`` and ``pyflowcharts explore``."""

from __future__ import annotations

import argparse

from pyflowcharts.ir import ChartOptions


def exclude_pattern(text: str) -> str:
    if text.rstrip("/") == "":
        raise argparse.ArgumentTypeError(f"must name a file or directory, got {text!r}")
    return text


def positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {text!r}")
    return value


def add_chart_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--variables", action="store_true", help="show plain variable assignments")
    parser.add_argument(
        "--no-parameters", action="store_true", help="hide parameters in the start node"
    )
    parser.add_argument(
        "--no-returns", action="store_true", help="hide returned values in return nodes"
    )
    parser.add_argument("--no-module", action="store_true", help="never chart module-level code")
    parser.add_argument(
        "--exclude",
        nargs="+",
        action="extend",
        default=[],
        type=exclude_pattern,
        metavar="GLOB",
        help="skip matching files and directories when walking a directory; a pattern "
        "without '/' matches names, one with '/' the relative path, and a trailing '/' "
        "matches directories only; repeatable",
    )
    parser.add_argument(
        "--max-label",
        type=positive_int,
        default=ChartOptions().max_label_length,
        metavar="N",
        help="truncate node labels to N characters (default: 60)",
    )


def chart_options(args: argparse.Namespace) -> ChartOptions:
    return ChartOptions(
        show_variables=args.variables,
        show_parameters=not args.no_parameters,
        show_returns=not args.no_returns,
        max_label_length=args.max_label,
        show_module=not args.no_module,
    )
