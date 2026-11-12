"""Graph invariants over a corpus of nested control-flow shapes (try/finally inside loops etc.)."""

import textwrap

import pytest
from conftest import assert_graph_integrity

from pyflowcharts.frontends.python_ast import PythonFrontend
from pyflowcharts.ir import ChartOptions

CORPUS = {
    "nested_finally_breaks": """
        def f():
            for i in x:
                try:
                    break
                finally:
                    for k in y:
                        try:
                            break
                        finally:
                            w()
    """,
    "finally_in_finally_continue": """
        def f():
            while c:
                try:
                    try:
                        continue
                    finally:
                        a()
                finally:
                    try:
                        b()
                    finally:
                        if d:
                            continue
    """,
    "break_in_try_else": """
        def f():
            for i in x:
                try:
                    a()
                except E:
                    continue
                else:
                    break
                finally:
                    b()
    """,
    "nested_def_in_finally_copy": """
        def f():
            for i in x:
                try:
                    if i:
                        break
                    continue
                finally:
                    def g():
                        return 1
                    match i:
                        case 1:
                            h()
    """,
}


@pytest.mark.parametrize("name", sorted(CORPUS))
def test_corpus_graph_integrity(name):
    src = textwrap.dedent(CORPUS[name]).encode()
    for chart in PythonFrontend().parse(src, f"{name}.py", ChartOptions()).document.functions:
        assert_graph_integrity(chart)
