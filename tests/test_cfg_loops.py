from conftest import chart_of, flow

from pyflowcharts.ir import NodeKind


def test_for_with_break_continue_else():
    c = chart_of("""
        def f(xs):
            for x in xs:
                if x:
                    continue
                if x is None:
                    break
                work(x)
            else:
                nobreak()
            after()
    """)
    assert {
        ("for x in xs", "if x", "next"),
        ("if x", "for x in xs", "True"),
        ("if x", "if x is None", "False"),
        ("if x is None", "after()", "True"),
        ("if x is None", "work(x)", "False"),
        ("work(x)", "for x in xs", None),
        ("for x in xs", "nobreak()", "done"),
        ("nobreak()", "after()", None),
    } <= flow(c)
    assert ("if x is None", "nobreak()", "True") not in flow(c)
    assert next(n for n in c.nodes if n.label == "for x in xs").kind is NodeKind.LOOP


def test_while():
    c = chart_of("def f(n):\n    while n > 0:\n        n = step(n)\n    return n\n")
    assert flow(c) == {
        ("def f(n)", "while n > 0", None),
        ("while n > 0", "n = step(n)", "True"),
        ("n = step(n)", "while n > 0", None),
        ("while n > 0", "return n", "False"),
        ("return n", "end", None),
    }


def test_while_true_exits_only_via_break():
    c = chart_of("def f():\n    while True:\n        if poll():\n            break\n    done()\n")
    assert not any(s == "while True" and t == "done()" for s, t, _ in flow(c))
    assert {("if poll()", "done()", "True"), ("if poll()", "while True", "False")} <= flow(c)


def test_nested_loops_break_inner_only():
    c = chart_of(
        "def f(A, B):\n    for a in A:\n        for b in B:\n            break\n        x()\n"
    )
    assert {
        ("for b in B", "x()", "next"),
        ("for b in B", "x()", "done"),
        ("x()", "for a in A", None),
    } <= flow(c)


def test_async_for_label():
    c = chart_of("async def f(s):\n    async for x in s:\n        use(x)\n")
    assert "async for x in s" in {n.label for n in c.nodes}
