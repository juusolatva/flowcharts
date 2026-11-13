"""Frontend protocol and errors shared by all language frontends."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol

from pyflowcharts.ir import ChartOptions, Document


class SourceError(Exception):
    """A source file could not be read or parsed. ``str()`` is a user-facing message."""

    def __init__(self, path: str, message: str, line: int | None = None) -> None:
        super().__init__(path, message, line)
        self.path = path
        self.message = message
        self.line = line

    def __str__(self) -> str:
        where = self.path if self.line is None else f"{self.path}:{self.line}"
        return f"{where}: error: {self.message}"


class UnsupportedLanguageError(SourceError):
    """No frontend handles the file's extension."""


@dataclass(frozen=True)
class Diagnostic:
    """A problem that did not stop the file from being charted (e.g. a skipped function).

    ``qualname`` names the skipped function, or is ``None`` for an error outside functions.
    """

    path: str
    line: int | None
    message: str
    qualname: str | None

    def __str__(self) -> str:
        where = self.path if self.line is None else f"{self.path}:{self.line}"
        return f"{where}: warning: {self.message}"


@dataclass(frozen=True)
class ParseResult:
    document: Document
    warnings: tuple[Diagnostic, ...]


class Frontend(Protocol):
    language: str
    extensions: tuple[str, ...]

    def parse(
        self,
        source: bytes,
        path: str,
        options: ChartOptions,
        key: PurePosixPath | None = None,
    ) -> ParseResult:
        """Parse one file. ``key`` is its output key (``pkg/io/load``), from which the module
        name is derived; ``None`` means the file's stem."""
        ...
