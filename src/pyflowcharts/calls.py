"""Link calls to the charts of a run: each call's target is its first candidate charted."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from pyflowcharts.ir import Call, CallRef, Chart, Document


def link(documents: list[Document]) -> list[Document]:
    """New documents whose calls have ``target`` set to the first candidate found among the
    run's function charts, or ``None``. Module charts are never targets. Documents with no
    module name, or one shared by several documents, are not indexed, so the result does not
    depend on document order."""
    names = Counter(doc.module_name for doc in documents)
    index = {
        CallRef(doc.module_name, chart.qualname)
        for doc in documents
        if doc.module_name and names[doc.module_name] == 1
        for chart in doc.functions
    }
    return [
        replace(
            doc,
            functions=[_linked(chart, index) for chart in doc.functions],
            module=None if doc.module is None else _linked(doc.module, index),
        )
        for doc in documents
    ]


def _linked[C: Chart](chart: C, index: set[CallRef]) -> C:
    return replace(chart, calls=[_target(call, index) for call in chart.calls])


def _target(call: Call, index: set[CallRef]) -> Call:
    target = next((ref for ref in call.candidates if ref in index), None)
    return replace(call, target=target)


def resolved_edges(documents: list[Document]) -> list[tuple[tuple[int, str], tuple[int, str]]]:
    """Sorted, deduplicated ``(document index, chart qualname)`` caller → callee pairs for the
    calls whose target is a function chart. Documents with no module name, or one shared by
    several documents, are not indexed (the linker's rule). Module charts can be callers."""
    names = Counter(doc.module_name for doc in documents)
    drawn = {
        (doc.module_name, chart.qualname): (i, chart.qualname)
        for i, doc in enumerate(documents)
        if doc.module_name and names[doc.module_name] == 1
        for chart in doc.functions
    }
    edges: set[tuple[tuple[int, str], tuple[int, str]]] = set()
    for i, doc in enumerate(documents):
        for chart in [*doc.functions, *([doc.module] if doc.module is not None else [])]:
            targets = (
                drawn.get((call.target.module, call.target.qualname))
                for call in chart.calls
                if call.target is not None
            )
            edges.update(((i, chart.qualname), t) for t in targets if t is not None)
    return sorted(edges)
