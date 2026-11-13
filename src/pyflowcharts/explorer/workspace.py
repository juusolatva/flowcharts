"""The explorer's view of a run: re-parse when files change, publish immutable snapshots."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pyflowcharts.calls import resolved_edges
from pyflowcharts.frontends.base import ParseResult
from pyflowcharts.inputs import Expansion, Input, drop_duplicate_keys, expand
from pyflowcharts.ir import ChartOptions, Document
from pyflowcharts.pipeline import Parsed, parse_all

Fingerprint = tuple[Any, ...]


@dataclass(frozen=True)
class FunctionSpan:
    qualname: str
    line: int
    end_line: int


@dataclass(frozen=True)
class Skipped:
    qualname: str
    line: int | None
    message: str


@dataclass(frozen=True)
class Entry:
    key: str
    source: str
    doc: int | None
    module_name: str
    functions: tuple[FunctionSpan, ...]
    has_module: bool
    skipped: tuple[Skipped, ...]
    error: str | None
    empty: bool


@dataclass(frozen=True)
class Snapshot:
    generation: int
    documents: tuple[Document, ...]
    results: tuple[ParseResult, ...]
    entries: tuple[Entry, ...]
    messages: tuple[str, ...]
    edges: tuple[tuple[tuple[int, str], tuple[int, str]], ...]
    svg_cache: dict[Any, bytes] = field(default_factory=dict, compare=False)
    svg_lock: threading.Lock = field(default_factory=threading.Lock, compare=False)


def snapshot_json(snapshot: Snapshot) -> dict[str, Any]:
    return {
        "generation": snapshot.generation,
        "entries": [
            {
                "key": e.key,
                "source": e.source,
                "doc": e.doc,
                "module_name": e.module_name,
                "functions": [
                    {"qualname": f.qualname, "line": f.line, "end_line": f.end_line}
                    for f in e.functions
                ],
                "has_module": e.has_module,
                "skipped": [
                    {"qualname": s.qualname, "line": s.line, "message": s.message}
                    for s in e.skipped
                ],
                "error": e.error,
                "empty": e.empty,
            }
            for e in snapshot.entries
        ],
        "messages": list(snapshot.messages),
        "edges": [[list(a), list(b)] for a, b in snapshot.edges],
    }


def _stat(path: Path) -> tuple[Any, ...]:
    try:
        st = path.stat()
    except OSError:
        return ("unreadable",)
    return (st.st_mtime_ns, st.st_size)


@dataclass(frozen=True)
class _Scan:
    expansion: Expansion
    kept: list[Input]
    duplicates: list[str]
    fingerprint: Fingerprint


class Workspace:
    SETTLE_INTERVAL = 0.3
    SETTLE_CAP = 2.0

    def __init__(
        self,
        paths: list[Path],
        excludes: list[str],
        options: ChartOptions,
        *,
        clock: Callable[[], float] = time.monotonic,
        stop: threading.Event | None = None,
    ) -> None:
        self._paths = paths
        self._excludes = excludes
        self._options = options
        self._clock = clock
        self._stop = stop if stop is not None else threading.Event()
        self._lock = threading.Lock()
        scan = self._scan()
        self._last = scan.fingerprint
        snapshot, self._failed, self._startup = self._build(1, scan)
        self._snapshot = snapshot

    def current(self) -> Snapshot:
        with self._lock:
            return self._snapshot

    def startup_failed(self) -> bool:
        """No document parsed and the last parse hit an expansion or read error."""
        return self._failed

    def startup_messages(self) -> list[str]:
        return list(self._startup)

    def refresh(self) -> bool:
        """Re-parse if the files changed (after the settle rule). ``True`` if it re-parsed."""
        scan = self._scan()
        if scan.fingerprint == self._last:
            return False
        first_seen = self._clock()
        while True:
            if self._stop.wait(self.SETTLE_INTERVAL):
                return False
            again = self._scan()
            settled = again.fingerprint == scan.fingerprint
            scan = again
            if settled or self._clock() - first_seen >= self.SETTLE_CAP:
                break
        self._last = scan.fingerprint
        snapshot, self._failed, _ = self._build(self._snapshot.generation + 1, scan)
        with self._lock:
            self._snapshot = snapshot
        return True

    def _scan(self) -> _Scan:
        expansion = expand(self._paths, self._excludes)
        kept, duplicates = drop_duplicate_keys(expansion.inputs)
        fingerprint = (
            tuple((str(i.path), i.key.as_posix(), _stat(i.path)) for i in kept),
            tuple(expansion.warnings),
            tuple(expansion.errors),
        )
        return _Scan(expansion, kept, duplicates, fingerprint)

    def _build(self, generation: int, scan: _Scan) -> tuple[Snapshot, bool, list[str]]:
        parsed = parse_all(scan.kept, self._options)
        documents = tuple(result.document for _, result in parsed.results)
        startup = [
            *scan.expansion.warnings,
            *scan.expansion.errors,
            *scan.duplicates,
            *parsed.read_errors,
        ]
        snapshot = Snapshot(
            generation=generation,
            documents=documents,
            results=tuple(result for _, result in parsed.results),
            entries=_entries(scan.kept, parsed),
            messages=(*startup, *_parse_messages(parsed)),
            edges=tuple(resolved_edges(list(documents))),
        )
        failed = not documents and bool(scan.expansion.errors or parsed.read_errors)
        return snapshot, failed, startup


def _parse_messages(parsed: Parsed) -> list[str]:
    messages = [
        str(w) for _, result in parsed.results for w in result.warnings if w.qualname is None
    ]
    messages += [
        f"warning: {item.path}: nothing to chart"
        for item, result in parsed.results
        if item.explicit and _empty(result)
    ]
    return messages


def _empty(result: ParseResult) -> bool:
    doc = result.document
    return not doc.functions and doc.module is None and not result.warnings


def _entries(kept: list[Input], parsed: Parsed) -> tuple[Entry, ...]:
    index = {item.path: i for i, (item, _) in enumerate(parsed.results)}
    entries: list[Entry] = []
    for item in kept:
        key, source = item.key.as_posix(), str(item.path)
        if (error := parsed.errors.get(item.path)) is not None:
            entries.append(Entry(key, source, None, "", (), False, (), error, False))
            continue
        i = index[item.path]
        result = parsed.results[i][1]
        doc = result.document
        entries.append(
            Entry(
                key=key,
                source=source,
                doc=i,
                module_name=doc.module_name,
                functions=tuple(
                    FunctionSpan(f.qualname, f.location.line, f.location.end_line)
                    for f in doc.functions
                ),
                has_module=doc.module is not None,
                skipped=tuple(
                    Skipped(w.qualname, w.line, w.message)
                    for w in result.warnings
                    if w.qualname is not None
                ),
                error=None,
                empty=_empty(result),
            )
        )
    return tuple(entries)
