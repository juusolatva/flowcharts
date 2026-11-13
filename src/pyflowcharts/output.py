"""Write documents to disk in the selected formats."""

from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath

import graphviz

from pyflowcharts.backends.dot import render, to_dot
from pyflowcharts.backends.mermaid import to_mermaid
from pyflowcharts.ir import Chart, Document
from pyflowcharts.serialize import to_json

EXTENSIONS = {"dot": "dot", "svg": "svg", "png": "png", "mermaid": "mmd"}

GRAPHVIZ_MISSING = (
    "error: Graphviz 'dot' executable not found; install Graphviz "
    "(e.g. 'sudo apt install graphviz') or use --format json dot mermaid"
)


class Writer:
    """Writes the selected formats.

    Reports a missing Graphviz once (then skips images) and reports each file that
    cannot be written, continuing with the rest.
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
        base = self.outdir / key
        if "json" in self.formats:
            self._save(base.parent / f"{base.name}.json", to_json(doc))
        if doc.module is not None:
            self._chart(doc.module, base.parent, base.name)
        for chart in doc.functions:
            self._chart(chart, base, chart.qualname)

    def _chart(self, chart: Chart, directory: Path, name: str) -> None:
        for fmt in self.formats:
            target = directory / f"{name}.{EXTENSIONS.get(fmt, fmt)}"
            match fmt:
                case "dot":
                    self._save(target, to_dot(chart))
                case "mermaid":
                    self._save(target, to_mermaid(chart))
                case "svg" | "png" if not self.graphviz_missing:
                    try:
                        data = render(chart, fmt)
                    except graphviz.ExecutableNotFound:
                        print(GRAPHVIZ_MISSING, file=sys.stderr)
                        self.graphviz_missing = True
                    else:
                        self._save(target, data)

    def _mkdir(self, directory: Path) -> bool:
        """Create ``directory`` once. A failure is reported once and remembered, and covers
        the directories below it."""
        if directory not in self._dirs:
            if any(self._dirs.get(parent) is False for parent in directory.parents):
                self._dirs[directory] = False  # already reported for the parent
                return False
            try:
                directory.mkdir(parents=True, exist_ok=True)
                self._dirs[directory] = True
            except OSError as err:
                self._report(directory, err)
                self._dirs[directory] = False
        return self._dirs[directory]

    def _save(self, target: Path, data: str | bytes) -> None:
        if not self._mkdir(target.parent):
            return
        try:
            if isinstance(data, bytes):
                target.write_bytes(data)
            else:
                target.write_text(data, encoding="utf-8")
        except OSError as err:
            self._report(target, err)

    def _report(self, target: Path, err: OSError) -> None:
        print(f"error: cannot write {target}: {err.strerror or err}", file=sys.stderr)
        self.write_failed = True
