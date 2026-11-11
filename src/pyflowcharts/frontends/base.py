"""Frontend protocol and errors shared by all language frontends."""

from __future__ import annotations

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


class Frontend(Protocol):
    language: str
    extensions: tuple[str, ...]

    def parse(self, source: bytes, path: str, options: ChartOptions) -> Document: ...
