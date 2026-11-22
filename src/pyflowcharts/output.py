"""Write documents to disk in the selected formats."""

from __future__ import annotations

import contextlib
import os
import secrets
import stat
from collections.abc import Callable
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Literal

from pyflowcharts.backends.callgraph import (
    render_callgraph,
    to_callgraph_dot,
    to_callgraph_mermaid,
)
from pyflowcharts.backends.dot import render, to_dot
from pyflowcharts.backends.dot_runner import DotFailed, DotNotFound, Warn
from pyflowcharts.backends.mermaid import to_mermaid
from pyflowcharts.inputs import case_key
from pyflowcharts.ir import Chart, Document
from pyflowcharts.serialize import to_json
from pyflowcharts.text import report

EXTENSIONS = {"dot": "dot", "svg": "svg", "png": "png", "mermaid": "mmd"}

GRAPHVIZ_NOT_FOUND = (
    "error: Graphviz 'dot' executable not found; install Graphviz "
    "(e.g. 'sudo apt install graphviz')"
)
GRAPHVIZ_MISSING = GRAPHVIZ_NOT_FOUND + " or use --format json dot mermaid"


class _LinkRefused(Exception):
    """A directory on the way to an output is a symbolic link or junction."""

    def __init__(self, link: Path) -> None:
        self.link = link


class Writer:
    """Writes the selected formats.

    Reports a missing Graphviz once (then skips images) and reports each file that
    cannot be written, continuing with the rest.

    The output tree may come from someone else (the default ``flowcharts/`` of a checkout),
    so nothing is written through a link: a symbolic link or junction at OUTDIR or at a
    directory below it is refused, and each file is written to a new temporary file and
    then moved over the old name, which replaces a link there instead of following it.
    """

    def __init__(self, outdir: Path, formats: list[str]) -> None:
        self.outdir = outdir
        self.formats = formats
        self.graphviz_missing = False
        self.write_failed = False
        self._dirs: dict[Path, bool] = {}  # directory -> whether it could be created

    def write(self, doc: Document, key: PurePosixPath) -> None:
        """Write ``doc`` under ``OUTDIR/key``: ``key.json``, ``key.<ext>`` for the module chart
        and ``key/<qualname>.<ext>`` for each function chart. Directories are created only
        for files that are written."""
        if key.is_absolute() or not key.parts or ".." in key.parts:
            raise ValueError(f"output key {str(key)!r} is outside the output directory")
        base = self.outdir / key
        if "json" in self.formats:
            self._save(base.parent / f"{base.name}.json", to_json(doc))
        if doc.module is not None:
            self._chart(doc.module, base.parent, base.name)
        if any(f != "json" for f in self.formats):
            _warn_case_clashes(doc)
        for chart in doc.functions:
            self._chart(chart, base, chart.qualname)

    def write_callgraph(self, documents: list[Document]) -> None:
        """Write ``OUTDIR/callgraph.<ext>`` in the picture formats, unless no document has a
        chart."""
        if not any(doc.functions or doc.module is not None for doc in documents):
            return
        self._picture(
            self.outdir / "callgraph",
            lambda: to_callgraph_dot(documents),
            lambda: to_callgraph_mermaid(documents),
            lambda fmt, warn: render_callgraph(documents, fmt, warn=warn),
        )

    def _chart(self, chart: Chart, directory: Path, name: str) -> None:
        self._picture(
            directory / name,
            lambda: to_dot(chart),
            lambda: to_mermaid(chart),
            lambda fmt, warn: render(chart, fmt, warn=warn),
        )

    def _picture(
        self,
        base: Path,
        dot: Callable[[], str],
        mermaid: Callable[[], str],
        image: Callable[[Literal["svg", "png"], Warn], bytes],
    ) -> None:
        """Write ``base.<ext>`` for each picture format. The renderers are called lazily, so
        they are looked up when used."""
        for fmt in self.formats:
            target = base.parent / f"{base.name}.{EXTENSIONS.get(fmt, fmt)}"
            match fmt:
                case "dot":
                    self._save(target, dot())
                case "mermaid":
                    self._save(target, mermaid())
                case "svg" | "png" if not self.graphviz_missing:
                    try:
                        data = image(fmt, partial(_graphviz_warning, target))
                    except DotNotFound:
                        report(GRAPHVIZ_MISSING)
                        self.graphviz_missing = True
                    except DotFailed as err:
                        report(f"error: cannot render {target}: {err}")
                        self.write_failed = True
                    else:
                        self._save(target, data)

    def _mkdir(self, directory: Path) -> bool:
        """Create ``directory`` (OUTDIR or below it) once. A failure is reported once and
        remembered, and covers the directories below it."""
        if directory not in self._dirs:
            if any(self._dirs.get(parent) is False for parent in directory.parents):
                self._dirs[directory] = False  # already reported for the parent
                return False
            try:
                self._make_dirs(directory)
                self._dirs[directory] = True
            except _LinkRefused as refused:
                report(f"error: refusing to write through symbolic link {refused.link}")
                self.write_failed = True
                self._dirs[directory] = False
                self._dirs[refused.link] = False  # covers everything else below the link
            except OSError as err:
                self._report(directory, err)
                self._dirs[directory] = False
        return self._dirs[directory]

    def _make_dirs(self, directory: Path) -> None:
        """Create OUTDIR's parents as given, then OUTDIR and each directory below it on the
        way to ``directory``, refusing links."""
        self.outdir.parent.mkdir(parents=True, exist_ok=True)
        path = self.outdir
        for part in ("", *directory.relative_to(self.outdir).parts):
            path = path / part if part else path
            if path.is_symlink() or path.is_junction():
                raise _LinkRefused(path)
            path.mkdir(exist_ok=True)

    def _save(self, target: Path, data: str | bytes) -> None:
        if not self._mkdir(target.parent):
            return
        try:
            _replace(target, data)
        except OSError as err:
            self._report(target, err)

    def _report(self, target: Path, err: OSError) -> None:
        report(f"error: cannot write {target}: {err.strerror or err}")
        self.write_failed = True


_READ_WRITE = (
    stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH
)


def _replace(target: Path, data: str | bytes) -> None:
    """Write ``data`` to a new file beside ``target`` and move it over ``target``.

    The temporary file has a short random name (so any output name that fits also fits it)
    and is created exclusively, never through an existing name, with read and write
    permission as the umask allows. It gets no more access than a regular file already at
    ``target`` had, so a private export stays private. Text is written as
    ``Path.write_text`` would.
    """
    temporary = target.parent / f".{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(temporary, flags, _READ_WRITE)
    try:
        _restrict_to(fd, temporary, target)
        if isinstance(data, bytes):
            with os.fdopen(fd, "wb") as file:
                file.write(data)
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(data)
        os.replace(temporary, target)
    except BaseException:
        with contextlib.suppress(OSError):  # keep the error that got us here
            temporary.unlink(missing_ok=True)
        raise


def _restrict_to(fd: int, temporary: Path, target: Path) -> None:
    """Drop the permissions an existing regular file at ``target`` did not grant. A link
    there says nothing about our file, so it is not followed."""
    try:
        existing = target.lstat()
    except OSError:
        return
    if stat.S_ISREG(existing.st_mode):
        current = stat.S_IMODE(os.fstat(fd).st_mode)
        if current & ~existing.st_mode:
            os.chmod(temporary, current & existing.st_mode)


def _graphviz_warning(target: Path, message: str) -> None:
    """A problem Graphviz reported while still writing ``target`` (the exit code is
    unaffected, as before)."""
    report(f"warning: {target}: {message}")


def _warn_case_clashes(doc: Document) -> None:
    """Warn about function charts whose file names differ only in case."""
    groups: dict[str, list[str]] = {}
    for chart in doc.functions:
        groups.setdefault(case_key(chart.qualname), []).append(chart.qualname)
    for names in groups.values():
        if len(names) > 1:
            quoted = [f"'{name}'" for name in names]
            listed = f"{', '.join(quoted[:-1])} and {quoted[-1]}"
            report(
                f"warning: {doc.source}: functions {listed} differ only in case; their files "
                "overwrite each other on case-insensitive file systems"
            )
