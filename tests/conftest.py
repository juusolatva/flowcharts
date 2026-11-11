import textwrap

from pyflowcharts.frontends.python_ast import PythonFrontend
from pyflowcharts.ir import ChartOptions, FunctionChart


def chart_of(src: str, qualname: str = "f", **opts) -> FunctionChart:
    doc = PythonFrontend().parse(textwrap.dedent(src).encode(), "t.py", ChartOptions(**opts))
    return next(c for c in doc.functions if c.qualname == qualname)


def flow(chart: FunctionChart) -> set[tuple[str, str, str | None]]:
    label = {n.id: n.label for n in chart.nodes}
    return {(label[e.source], label[e.target], e.label) for e in chart.edges}
