import copy
import shutil
from dataclasses import replace
from pathlib import PurePosixPath

import pytest

from pyflowcharts.backends.callgraph import render_callgraph, to_callgraph_dot, to_callgraph_mermaid
from pyflowcharts.calls import link
from pyflowcharts.frontends.python import PythonFrontend
from pyflowcharts.ir import ChartOptions

needs_dot = pytest.mark.skipif(shutil.which("dot") is None, reason="Graphviz not installed")


def parse(src, key):
    return (
        PythonFrontend()
        .parse(src.encode(), f"{key}.py", ChartOptions(), PurePosixPath(key))
        .document
    )


def run(*files):  # files: (src, key)
    return link([parse(src, key) for src, key in files])


APP = (
    "from lib import g\ndef f():\n    g(g(1))\n    f()\nif __name__ == '__main__':\n    f()\n",
    "app",
)
LIB = ("def g(): pass\n", "lib")
EMPTY = ("", "pkg/__init__")


def test_dot_clusters_nodes_and_edges():
    dot = to_callgraph_dot(run(APP, LIB, EMPTY))
    assert "subgraph cluster_0" in dot
    assert "subgraph cluster_1" in dot
    assert "cluster_2" not in dot
    assert "label=app" in dot
    assert "label=lib" in dot
    assert dot.count('"0#f" -> "1#g"') == 1  # Review Focus 3
    assert '"0#f" -> "0#f"' in dot  # recursion self-loop
    assert '"0#<module>" -> "0#f"' in dot
    assert "rankdir=LR" in dot


def test_module_label_escaped_and_source_fallback_without_colon_ids():
    docs = run(APP, LIB)
    docs[0] = replace(docs[0], module_name="", source="C:/x/app.py")
    dot = to_callgraph_dot(docs)
    assert 'label="<module>"' in dot  # quoted, never an HTML-like label
    assert 'label="C:/x/app.py"' in dot  # cluster falls back to the source path
    assert all(":" not in line for line in dot.splitlines() if "->" in line)


def test_duplicate_module_names_get_distinct_nodes():
    docs = [parse("def f(): pass\n", "a.b"), parse("def f(): pass\n", "a/b")]
    dot = to_callgraph_dot(link(docs))
    assert '"0#f"' in dot
    assert '"1#f"' in dot


def test_only_drawn_targets_get_edges():
    docs = run(APP, LIB)
    docs[1] = replace(docs[1], functions=[])  # as if --function dropped g
    dot = to_callgraph_dot(docs)
    assert "1#g" not in dot
    assert "cluster_1" not in dot


def test_mermaid_generated_ids_and_keyword_safe():
    mmd = to_callgraph_mermaid(run(APP, LIB, ("def g(): pass\n", "end")))
    assert mmd.startswith("flowchart LR")
    assert 'subgraph s0 ["app"]' in mmd
    assert "subgraph end" not in mmd
    assert 'subgraph s2 ["end"]' in mmd
    assert "#60;module#62;" in mmd


def test_non_ascii_qualnames():  # Review Focus 5
    docs = run(("def größe(): pass\ndef f():\n    größe()\n", "m"))
    assert '"0#f" -> "0#größe"' in to_callgraph_dot(docs)
    assert "größe" in to_callgraph_mermaid(docs)


def test_deterministic():
    docs = run(APP, LIB)
    assert to_callgraph_dot(docs) == to_callgraph_dot(copy.deepcopy(docs))
    assert to_callgraph_mermaid(docs) == to_callgraph_mermaid(copy.deepcopy(docs))


@needs_dot
def test_svg_renders():
    assert b"<svg" in render_callgraph(run(APP, LIB), "svg")
