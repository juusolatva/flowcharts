from conftest import chart_of, flow

from pyflowcharts.ir import NodeKind


def test_if_elif_else():
    c = chart_of("""
        def f(x):
            if x > 0:
                a()
            elif x < 0:
                b()
            else:
                c()
            d()
    """)
    assert flow(c) == {
        ("def f(x)", "if x > 0", None),
        ("if x > 0", "a()", "True"),
        ("if x > 0", "if x < 0", "False"),
        ("if x < 0", "b()", "True"),
        ("if x < 0", "c()", "False"),
        ("a()", "d()", None),
        ("b()", "d()", None),
        ("c()", "d()", None),
        ("d()", "end", None),
    }
    assert next(n for n in c.nodes if n.label == "if x > 0").kind is NodeKind.DECISION


def test_if_without_else_falls_through():
    c = chart_of("def f(x):\n    if x:\n        a()\n    b()\n")
    assert {("if x", "a()", "True"), ("if x", "b()", "False"), ("a()", "b()", None)} <= flow(c)


def test_if_with_pass_body():
    c = chart_of("def f(x):\n    if x:\n        pass\n    b()\n")
    assert {("if x", "b()", "True"), ("if x", "b()", "False")} <= flow(c)


def test_if_branch_returning():
    c = chart_of("def f(x):\n    if x:\n        return 1\n    b()\n")
    assert ("return 1", "b()", None) not in flow(c)
    assert {("return 1", "end", None), ("if x", "b()", "False")} <= flow(c)


def test_match_without_wildcard():
    c = chart_of("""
        def f(cmd):
            match cmd:
                case "go":
                    go()
                case [x, *_] if x:
                    other(x)
            done()
    """)
    assert {
        ("match cmd", "go()", 'case "go"'),
        ("match cmd", "other(x)", "case [x, *_] if x"),
        ("match cmd", "done()", "no match"),
        ("go()", "done()", None),
        ("other(x)", "done()", None),
    } <= flow(c)


def test_match_with_wildcard_has_no_fallthrough():
    c = chart_of(
        "def f(v):\n    match v:\n        case 1:\n            a()\n        case _:\n            b()\n"
    )
    assert {("match v", "a()", "case 1"), ("match v", "b()", "case _")} <= flow(c)
    assert all(lbl != "no match" for _, _, lbl in flow(c))
