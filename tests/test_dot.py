import shutil
from pathlib import Path

import pytest
from conftest import chart_of

from pyflowcharts.backends.dot import SHAPES, render, to_dot
from pyflowcharts.frontends.python import PythonFrontend
from pyflowcharts.ir import ChartOptions

needs_dot = pytest.mark.skipif(shutil.which("dot") is None, reason="Graphviz not installed")
IF_SRC = "def f(x):\n    if x > 0:\n        return 1\n    g()\n"


def line_for(src: str, node_id: str) -> str:
    return next(line for line in src.splitlines() if line.strip().startswith(f'"{node_id}" ['))


def test_nodes_have_shapes_and_tooltips():
    c = chart_of(IF_SRC)
    src = to_dot(c)
    for n in c.nodes:
        assert f"shape={SHAPES[n.kind]}" in line_for(src, n.id)
    decision = next(n.id for n in c.nodes if n.label == "if x > 0")
    assert 'tooltip="line 2"' in line_for(src, decision)


def test_edge_labels():
    src = to_dot(chart_of(IF_SRC))
    assert "label=True" in src and "label=False" in src


def test_label_escaping():
    src = to_dot(chart_of('def f():\n    print("a\\nb", "it\'s")\n'))
    assert r"""print(\"a\\nb\", \"it's\")""" in src


def test_deterministic():
    assert to_dot(chart_of(IF_SRC)) == to_dot(chart_of(IF_SRC))


@needs_dot
def test_render_svg_and_png():
    c = chart_of(IF_SRC)
    assert b"<svg" in render(c, "svg")
    assert render(c, "png")[:8] == b"\x89PNG\r\n\x1a\n"


@needs_dot
def test_renders_whole_fixture():  # every fixture chart is valid DOT
    path = Path(__file__).parent / "fixtures" / "sample.py"
    for chart in (
        PythonFrontend().parse(path.read_bytes(), str(path), ChartOptions()).document.functions
    ):
        assert b"<svg" in render(chart, "svg")


def test_exception_edges_are_dashed():
    src = to_dot(chart_of("def f():\n    try:\n        a()\n    except E:\n        h()\n"))
    dashed = [line for line in src.splitlines() if "style=dashed" in line]
    assert len(dashed) == 1 and "label=exception" in dashed[0]
