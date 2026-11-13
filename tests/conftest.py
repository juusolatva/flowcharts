import textwrap

from pyflowcharts.frontends.python import PythonFrontend
from pyflowcharts.ir import Chart, ChartOptions, FunctionChart


def chart_of(src: str, qualname: str = "f", **opts) -> FunctionChart:
    doc = (
        PythonFrontend().parse(textwrap.dedent(src).encode(), "t.py", ChartOptions(**opts)).document
    )
    return next(c for c in doc.functions if c.qualname == qualname)


def flow(chart: Chart) -> set[tuple[str, str, str | None]]:
    label = {n.id: n.label for n in chart.nodes}
    return {(label[e.source], label[e.target], e.label) for e in chart.edges}


def assert_graph_integrity(chart: Chart) -> None:
    """Invariants every chart must satisfy: unique IDs, no ':' in IDs, edges between real nodes."""
    ids = [n.id for n in chart.nodes]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"{chart.qualname}: duplicate node ids {duplicates}"
    assert not any(":" in i for i in ids), chart.qualname
    known = set(ids)
    assert all(e.source in known and e.target in known for e in chart.edges), chart.qualname
