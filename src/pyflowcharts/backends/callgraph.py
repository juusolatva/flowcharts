"""The run's call graph: one node per chart, clustered by file, one edge per resolved
caller → callee pair."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

import graphviz

from pyflowcharts.backends.mermaid import escape
from pyflowcharts.ir import MODULE_QUALNAME, Document

type _Key = tuple[int, str]  # (document index, chart qualname)


@dataclass(frozen=True)
class _Cluster:
    index: int
    label: str
    charts: list[str]  # qualnames: function charts in order, then the module chart


def _layout(documents: list[Document]) -> tuple[list[_Cluster], list[tuple[_Key, _Key]]]:
    """Clusters for the documents that have charts, and the sorted, deduplicated edges
    between drawn charts."""
    clusters = []
    for i, doc in enumerate(documents):
        charts = [c.qualname for c in doc.functions]
        if doc.module is not None:
            charts.append(MODULE_QUALNAME)
        if charts:
            clusters.append(_Cluster(i, doc.module_name or doc.source, charts))
    # The linker's index rule: no empty and no shared module names.
    names = Counter(doc.module_name for doc in documents)
    drawn = {
        (doc.module_name, chart.qualname): (i, chart.qualname)
        for i, doc in enumerate(documents)
        if doc.module_name and names[doc.module_name] == 1
        for chart in doc.functions
    }
    edges: set[tuple[_Key, _Key]] = set()
    for i, doc in enumerate(documents):
        charts = [*doc.functions, *([doc.module] if doc.module is not None else [])]
        for chart in charts:
            for call in chart.calls:
                if call.target is None:
                    continue
                target = drawn.get((call.target.module, call.target.qualname))
                if target is not None:
                    edges.add(((i, chart.qualname), target))
    return clusters, sorted(edges)


def _dot_id(key: _Key) -> str:
    return f"{key[0]}#{key[1]}"


def to_callgraph_digraph(documents: list[Document]) -> graphviz.Digraph:
    clusters, edges = _layout(documents)
    graph = graphviz.Digraph(
        graphviz.nohtml("callgraph"),
        graph_attr={"rankdir": "LR"},
        node_attr={"fontname": "Helvetica", "shape": "box"},
        edge_attr={"fontname": "Helvetica"},
    )
    for cluster in clusters:
        with graph.subgraph(
            name=f"cluster_{cluster.index}",
            graph_attr={"label": graphviz.escape(cluster.label)},
            node_attr={},
            edge_attr={},
        ) as sub:
            for qualname in cluster.charts:
                sub.node(_dot_id((cluster.index, qualname)), label=graphviz.escape(qualname))
    for source, target in edges:
        graph.edge(_dot_id(source), _dot_id(target))
    return graph


def to_callgraph_dot(documents: list[Document]) -> str:
    return to_callgraph_digraph(documents).source


def render_callgraph(documents: list[Document], fmt: Literal["svg", "png"]) -> bytes:
    """Render with Graphviz. Raises ``graphviz.ExecutableNotFound`` if ``dot`` is missing."""
    return to_callgraph_digraph(documents).pipe(format=fmt)


def to_callgraph_mermaid(documents: list[Document]) -> str:
    clusters, edges = _layout(documents)
    ids: dict[_Key, str] = {}
    lines = ["flowchart LR"]
    for cluster in clusters:
        lines.append(f'    subgraph s{cluster.index} ["{escape(cluster.label)}"]')
        for qualname in cluster.charts:
            node_id = ids[(cluster.index, qualname)] = f"n{len(ids)}"
            lines.append(f'        {node_id}["{escape(qualname)}"]')
        lines.append("    end")
    lines += [f"    {ids[source]} --> {ids[target]}" for source, target in edges]
    return "\n".join(lines) + "\n"
