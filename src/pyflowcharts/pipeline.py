"""Parse the inputs of a run and link their calls; shared by the CLI and the explorer."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from pyflowcharts.calls import link
from pyflowcharts.frontends import SourceError, frontend_for_path
from pyflowcharts.frontends.base import ParseResult
from pyflowcharts.inputs import Input
from pyflowcharts.ir import ChartOptions


@dataclass(frozen=True)
class Parsed:
    results: list[tuple[Input, ParseResult]]
    read_errors: list[str]  # user-facing messages, in input order
    errors: dict[Path, str]  # the same messages by file


def parse_all(inputs: list[Input], options: ChartOptions) -> Parsed:
    """Parse every input in order and link the calls across the run. Files that could not
    be read are reported in ``read_errors``/``errors``; nothing is printed."""
    parsed: list[tuple[Input, ParseResult]] = []
    read_errors: list[str] = []
    errors: dict[Path, str] = {}
    for item in inputs:
        try:
            parsed.append((item, _parse_file(item.path, options, item.key)))
        except SourceError as err:
            read_errors.append(str(err))
            errors[item.path] = str(err)
    linked = link([result.document for _, result in parsed])
    results = [
        (item, replace(result, document=doc))
        for (item, result), doc in zip(parsed, linked, strict=True)
    ]
    return Parsed(results, read_errors, errors)


def _parse_file(path: Path, options: ChartOptions, key: PurePosixPath) -> ParseResult:
    frontend = frontend_for_path(path)
    try:
        source = path.read_bytes()
    except FileNotFoundError:
        raise SourceError(str(path), "no such file") from None
    except OSError as err:
        raise SourceError(str(path), err.strerror or str(err)) from None
    return frontend.parse(source, str(path), options, key)
