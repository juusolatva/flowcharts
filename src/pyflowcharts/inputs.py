"""Turn ``PATH`` arguments into the files to chart and the output key of each.

A file argument is charted as given. A directory argument is walked recursively; the files
found get output keys relative to it, so the output tree mirrors the source tree.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from pyflowcharts.frontends import supported_extensions

_SKIPPED_DIRS = frozenset({"__pycache__"})
_HINT = "run them separately with different --output directories"


@dataclass(frozen=True)
class Input:
    path: Path
    key: PurePosixPath  # output path relative to OUTDIR, without extension
    explicit: bool  # named on the command line (not only found by a walk)


@dataclass(frozen=True)
class Expansion:
    inputs: list[Input]
    warnings: list[str] = field(default_factory=list)  # complete lines, ready to print
    errors: list[str] = field(default_factory=list)


def expand(paths: list[Path], excludes: list[str]) -> Expansion:
    """Expand files and directories into deduplicated inputs, in argument order.

    A path that is not a directory (even a missing one) is passed through; parsing reports
    any problem with it. ``excludes`` apply only to files found by a walk.
    """
    found: list[Input] = []
    warnings: list[str] = []
    errors: list[str] = []
    for path in paths:
        if not path.is_dir():
            found.append(Input(path, PurePosixPath(path.stem), explicit=True))
            continue
        walk_errors: list[str] = []
        walked = _walk(path, excludes, walk_errors)
        errors += walk_errors
        if not walked and not walk_errors:
            warnings.append(f"warning: {path}: no source files found")
        found += walked
    return Expansion(_dedupe(found), warnings, errors)


def _walk(top: Path, excludes: list[str], errors: list[str]) -> list[Input]:
    def report(err: OSError) -> None:
        errors.append(f"{err.filename or top}: error: cannot read directory: {err.strerror or err}")

    extensions = supported_extensions()
    found: list[tuple[tuple[str, ...], Input]] = []
    for dirpath, dirnames, filenames in os.walk(top, onerror=report):
        directory = Path(dirpath)
        rel_dir = PurePosixPath(*directory.relative_to(top).parts)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not name.startswith(".")
            and name not in _SKIPPED_DIRS
            and not (directory / name).is_symlink()
            and not _excluded(rel_dir / name, True, excludes)
        )
        for name in filenames:
            path = directory / name
            rel = rel_dir / name
            if (
                name.startswith(".")
                or path.suffix.lower() not in extensions
                or not path.is_file()
                or _excluded(rel, False, excludes)
            ):
                continue
            key = rel.parent / PurePosixPath(name).stem
            found.append((rel.parts, Input(path, key, explicit=False)))
    found.sort(key=lambda item: item[0])
    return [item for _, item in found]


def _excluded(rel: PurePosixPath, is_dir: bool, excludes: list[str]) -> bool:
    """A pattern without ``/`` matches any file or directory name; one with ``/`` matches the
    path relative to the walked directory. A trailing ``/`` restricts it to directories."""
    for pattern in excludes:
        dir_only = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        if dir_only and not is_dir:
            continue
        target = rel.as_posix() if "/" in pattern else rel.name
        if fnmatch.fnmatchcase(target, pattern):
            return True
    return False


def _dedupe(found: list[Input]) -> list[Input]:
    """One input per file (by resolved path): the first way it was reached, explicit if any
    way was."""
    by_file: dict[Path, Input] = {}
    for item in found:
        key = item.path.resolve()
        if key not in by_file:
            by_file[key] = item
        elif item.explicit and not by_file[key].explicit:
            first = by_file[key]
            by_file[key] = Input(first.path, first.key, explicit=True)
    return list(by_file.values())


def collision_error(inputs: list[Input]) -> str | None:
    """The error for two inputs whose outputs would overlap, or ``None``: the same key, or
    one key whose segments are a proper prefix of another's (``OUTDIR/K/`` is shared)."""
    by_key: dict[tuple[str, ...], Input] = {}
    for item in inputs:
        parts = item.key.parts
        if parts in by_key:
            first = by_key[parts]
            return (
                f"error: output name collision: {first.path} and {item.path} "
                f"both map to '{item.key}'; {_HINT}"
            )
        by_key[parts] = item
    for item in inputs:
        parts = item.key.parts
        for n in range(1, len(parts)):
            if (short := by_key.get(parts[:n])) is not None:
                return (
                    f"error: output name collision: {short.path} maps to '{short.key}' and "
                    f"{item.path} to '{item.key}', which would share the directory "
                    f"'{short.key}'; {_HINT}"
                )
    return None
