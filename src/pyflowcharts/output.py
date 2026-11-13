"""Write documents to disk in the selected formats."""

from __future__ import annotations

import sys
from pathlib import Path

import graphviz

from pyflowcharts.backends.dot import render, to_dot
from pyflowcharts.backends.mermaid import to_mermaid
from pyflowcharts.ir import Document
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

    def write(self, doc: Document, stem: str) -> None:
        if not self._mkdir(self.outdir):
            return
        if "json" in self.formats:
            self._save(self.outdir / f"{stem}.json", to_json(doc))
        per_function = [fmt for fmt in self.formats if fmt != "json"]
        if not per_function or not doc.functions:
            return
        chart_dir = self.outdir / stem
        if not self._mkdir(chart_dir):
            return
        for chart in doc.functions:
            for fmt in per_function:
                target = chart_dir / f"{chart.qualname}.{EXTENSIONS[fmt]}"
                match fmt:
                    case "dot":
                        self._save(target, to_dot(chart))
                    case "mermaid":
                        self._save(target, to_mermaid(chart))
                    case "svg" | "png" if not self.graphviz_missing:
                        try:
                            self._save(target, render(chart, fmt))
                        except graphviz.ExecutableNotFound:
                            print(GRAPHVIZ_MISSING, file=sys.stderr)
                            self.graphviz_missing = True

    def _mkdir(self, directory: Path) -> bool:
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            self._report(directory, err)
            return False
        return True

    def _save(self, target: Path, data: str | bytes) -> None:
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
