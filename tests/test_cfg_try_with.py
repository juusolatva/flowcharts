from pathlib import Path

from conftest import chart_of, flow

from pyflowcharts.frontends.python import PythonFrontend
from pyflowcharts.ir import ChartOptions, NodeKind


def test_try_except_else_finally():
    c = chart_of("""
        def f(path):
            try:
                data = load(path)
            except (OSError, ValueError) as e:
                log(e)
                return None
            except Exception:
                raise
            else:
                use(data)
            finally:
                cleanup()
            return data
    """)
    assert flow(c) == {
        ("def f(path)", "try", None),
        ("try", "data = load(path)", None),
        ("data = load(path)", "except (OSError, ValueError) as e", "exception"),
        ("data = load(path)", "except Exception", "exception"),
        ("except (OSError, ValueError) as e", "log(e)", None),
        ("log(e)", "return None", None),
        ("return None", "end", None),
        ("except Exception", "raise", None),
        ("data = load(path)", "use(data)", None),
        ("use(data)", "finally", None),
        ("finally", "cleanup()", None),
        ("cleanup()", "return data", None),
        ("return data", "end", None),
        ("except (OSError, ValueError) as e", "finally (exception)", "exception"),
        ("log(e)", "finally (exception)", "exception"),
        ("return None", "finally (exception)", "exception"),
        ("except Exception", "finally (exception)", "exception"),
        ("raise", "finally (exception)", "exception"),
        ("use(data)", "finally (exception)", "exception"),
        ("finally (exception)", "cleanup()", None),
        ("cleanup()", "end", None),
    }
    assert any(n.id.endswith("~finally") for n in c.nodes)


def succ(chart, node_id):
    return {e.target for e in chart.edges if e.source == node_id}


def node(chart, label):
    return next(n.id for n in chart.nodes if n.label == label)


def test_break_runs_finally_before_leaving_loop():
    c = chart_of("""
        def f(xs):
            for x in xs:
                try:
                    if x:
                        break
                    work(x)
                finally:
                    cleanup()
            after()
    """)
    assert {
        ("if x", "finally (break)", "True"),
        ("work(x)", "finally", None),
        ("for x in xs", "after()", "done"),
    } <= flow(c)
    (brk_cleanup,) = succ(c, node(c, "finally (break)"))
    (norm_cleanup,) = succ(c, node(c, "finally"))
    assert succ(c, brk_cleanup) == {node(c, "after()")}
    assert succ(c, norm_cleanup) == {node(c, "for x in xs")}
    assert "~break@L" in brk_cleanup and brk_cleanup != norm_cleanup


def test_finally_can_override_break():
    c = chart_of("""
        def f():
            while True:
                try:
                    break
                finally:
                    continue
            after()
    """)
    assert {("try", "finally (break)", None), ("finally (break)", "while True", None)} <= flow(c)
    assert node(c, "after()") not in {e.target for e in c.edges}  # loop never exits


def test_continue_runs_finally():
    c = chart_of("""
        def f(xs):
            for x in xs:
                try:
                    continue
                finally:
                    log(x)
    """)
    (cont_log,) = succ(c, node(c, "finally (continue)"))
    assert succ(c, cont_log) == {node(c, "for x in xs")}


def test_with_statement():
    c = chart_of("def f(p):\n    with open(p) as fh, lock:\n        read(fh)\n")
    assert flow(c) == {
        ("def f(p)", "with open(p) as fh, lock", None),
        ("with open(p) as fh, lock", "read(fh)", None),
        ("read(fh)", "end", None),
    }


def test_nested_def_is_a_node_and_its_own_chart():
    src = "def outer():\n    def inner(x):\n        return x\n    return inner\n"
    assert flow(chart_of(src, "outer")) == {
        ("def outer()", "def inner(x)", None),
        ("def inner(x)", "return inner", None),
        ("return inner", "end", None),
    }
    assert flow(chart_of(src, "outer.inner")) == {
        ("def inner(x)", "return x", None),
        ("return x", "end", None),
    }


def test_sample_fixture_graph_integrity():
    path = Path(__file__).parent / "fixtures" / "sample.py"
    doc = PythonFrontend().parse(path.read_bytes(), str(path), ChartOptions()).document
    assert len({c.qualname for c in doc.functions}) == len(doc.functions)
    for chart in doc.functions:
        ids = [n.id for n in chart.nodes]
        assert len(ids) == len(set(ids)), chart.qualname
        assert not any(":" in i for i in ids)
        assert all(e.source in ids and e.target in ids for e in chart.edges)
        assert all(n.kind is not NodeKind.PROCESS or "\n" not in n.label for n in chart.nodes)
