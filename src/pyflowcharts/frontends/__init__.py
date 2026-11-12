"""Language frontends: turn a source file into an IR ``Document``.

To add a language, implement the ``Frontend`` protocol and add an instance to ``FRONTENDS``.
"""

from __future__ import annotations

from pathlib import Path

from pyflowcharts.frontends.base import Frontend, SourceError, UnsupportedLanguageError
from pyflowcharts.frontends.python import PythonFrontend

FRONTENDS: tuple[Frontend, ...] = (PythonFrontend(),)


def frontend_for_path(path: Path) -> Frontend:
    suffix = path.suffix.lower()
    for frontend in FRONTENDS:
        if suffix in frontend.extensions:
            return frontend
    shown = f"'{path.suffix}'" if path.suffix else "(no extension)"
    raise UnsupportedLanguageError(str(path), f"unsupported file type {shown}")


__all__ = [
    "FRONTENDS",
    "Frontend",
    "SourceError",
    "UnsupportedLanguageError",
    "frontend_for_path",
]
