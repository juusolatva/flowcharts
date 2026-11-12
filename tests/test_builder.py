import pytest
from conftest import flow

from pyflowcharts.cfg.builder import StrayLoopTransfer, build_chart
from pyflowcharts.cfg.model import (
    Arm,
    Block,
    Branch,
    Break,
    Continue,
    Handler,
    Loop,
    Step,
    Terminal,
    Try,
)
from pyflowcharts.ir import ChartOptions, FunctionChart, NodeKind, SourceLocation

LOC = SourceLocation(1, 0, 1, 10)


def at(line: int, col: int = 4) -> SourceLocation:
    return SourceLocation(line, col, line, col + 1)


def chart(body: Block, **opts) -> FunctionChart:
    nodes, edges = build_chart("f", "def f()", LOC, body, ChartOptions(**opts))
    return FunctionChart("f", "f", False, [], None, LOC, nodes, edges)


def test_sequence_and_terminal():
    c = chart((Step("a()", at(2)), Terminal(NodeKind.RETURN, "return 1", at(3))))
    assert flow(c) == {
        ("def f()", "a()", None),
        ("a()", "return 1", None),
        ("return 1", "end", None),
    }
    assert [n.id for n in c.nodes] == ["f#start", "f#end", "f#L2C4", "f#L3C4"]
    assert c.nodes[0].kind is NodeKind.START and c.nodes[1].location is None


def test_hidden_steps_need_variables_option():
    body = (Step("n = 0", at(2), hidden=True), Step("g()", at(3)))
    assert "n = 0" not in {n.label for n in chart(body).nodes}
    assert "n = 0" in {n.label for n in chart(body, show_variables=True).nodes}


def test_reveal_rule_per_block():
    inner = (Step("n = 0", at(3), hidden=True),)
    other = (Step("n = 1", at(5), hidden=True), Step("g()", at(6)))
    body = (Branch("if a", at(2), (Arm("True", inner), Arm("False", other)), None),)
    labels = {n.label for n in chart(body).nodes}
    assert "n = 0" in labels and "n = 1" not in labels


def test_branch_default_falls_through():
    body = (
        Branch("if x", at(2), (Arm("True", (Step("a()", at(3)),)),), "False"),
        Step("b()", at(4)),
    )
    assert flow(chart(body)) == {
        ("def f()", "if x", None),
        ("if x", "a()", "True"),
        ("a()", "b()", None),
        ("if x", "b()", "False"),
        ("b()", "end", None),
    }


def test_step_with_body():
    body = (Step("with x", at(2), body=(Step("a()", at(3)),)),)
    assert flow(chart(body)) == {
        ("def f()", "with x", None),
        ("with x", "a()", None),
        ("a()", "end", None),
    }


def test_labels_and_edge_labels_are_shortened():
    body = (Branch("if " + "x" * 100, at(2), (Arm("case " + "y" * 100, ()),), None),)
    c = chart(body, max_label_length=10)
    assert "if xxxxxx…" in {n.label for n in c.nodes}
    assert {e.label for e in c.edges if e.label} == {"case yyyy…"}


# -- loops (Task 2) ---------------------------------------------------------


def test_loop_enter_exit_else_and_break():
    inner = (
        Branch("if x", at(3), (Arm("True", (Break(at(4)),)),), "False"),
        Step("work(x)", at(5)),
    )
    body = (
        Loop("for x in xs", at(2), "next", "done", inner, (Step("nobreak()", at(7)),)),
        Step("after()", at(8)),
    )
    assert flow(chart(body)) == {
        ("def f()", "for x in xs", None),
        ("for x in xs", "if x", "next"),
        ("if x", "after()", "True"),
        ("if x", "work(x)", "False"),
        ("work(x)", "for x in xs", None),
        ("for x in xs", "nobreak()", "done"),
        ("nobreak()", "after()", None),
        ("after()", "end", None),
    }


def test_continue_goes_to_loop_head():
    body = (Loop("while c", at(2), "True", "False", (Continue(at(3)), Step("dead()", at(4))), ()),)
    assert ("while c", "while c", "True") in flow(chart(body))


def test_loop_without_exit():
    body = (
        Loop("while True", at(2), "True", None, (Step("poll()", at(3)),), ()),
        Step("after()", at(4)),
    )
    f = flow(chart(body))
    assert ("while True", "after()", "False") not in f and not any(t == "after()" for _, t, _ in f)


def test_stray_break_raises():
    with pytest.raises(StrayLoopTransfer) as e:
        chart((Break(at(2)),))
    assert (e.value.kind, e.value.loc) == ("break", at(2))
    with pytest.raises(StrayLoopTransfer) as e:
        chart((Continue(at(3)),))
    assert e.value.kind == "continue"


# -- try / finally (Task 3) -------------------------------------------------


def try_stmt(line, body, handlers=(), orelse=(), finalbody=None):
    return Try(at(line), body, handlers, orelse, finalbody)


def test_try_except_else_finally():
    body = (
        try_stmt(
            2,
            (Step("load()", at(3)),),
            (Handler("except E", at(4), (Terminal(NodeKind.RETURN, "return", at(5)),)),),
            (Step("use()", at(7)),),
            (Step("cleanup()", at(9)),),
        ),
        Step("after()", at(10)),
    )
    assert flow(chart(body)) == {
        ("def f()", "try", None),
        ("try", "load()", None),
        ("load()", "except E", "exception"),
        ("except E", "return", None),
        ("return", "end", None),
        ("load()", "use()", None),
        ("use()", "finally", None),
        ("finally", "cleanup()", None),
        ("cleanup()", "after()", None),
        ("after()", "end", None),
    }


def test_empty_finalbody_still_gets_a_node():
    c = chart((try_stmt(2, (Step("a()", at(3)),), finalbody=()),))
    assert ("finally", "end", None) in flow(c) and any(n.id == "f#L2C4~finally" for n in c.nodes)


def test_no_finally_clause():
    c = chart((try_stmt(2, (Step("a()", at(3)),), (Handler("except", at(4), ()),)),))
    assert flow(c) == {
        ("def f()", "try", None),
        ("try", "a()", None),
        ("a()", "except", "exception"),
        ("a()", "end", None),
        ("except", "end", None),
    }


def test_every_body_node_points_at_every_handler():
    body = (
        try_stmt(
            2,
            (Branch("if x", at(3), (Arm("True", (Step("a()", at(4)),)),), "False"),),
            (Handler("except A", at(5), ()), Handler("except B", at(6), ())),
        ),
    )
    f = flow(chart(body))
    assert {(s, h, "exception") for s in ("if x", "a()") for h in ("except A", "except B")} <= f
    assert not any(s == "try" and lbl == "exception" for s, _, lbl in f)


def test_nested_try_body_points_only_at_inner_handlers():
    inner = try_stmt(3, (Step("a()", at(4)),), (Handler("except I", at(5), (Step("h()", at(6)),)),))
    outer = try_stmt(2, (inner,), (Handler("except O", at(7), ()),))
    f = flow(chart((outer,)))
    assert ("a()", "except I", "exception") in f and ("a()", "except O", "exception") not in f
    assert {("except I", "except O", "exception"), ("h()", "except O", "exception")} <= f
    # The inner try node is itself a statement of the outer body.
    assert ("try", "except O", "exception") in f


def test_try_pass_leaves_handlers_unreachable():
    c = chart((try_stmt(2, (), (Handler("except E", at(3), ()),)),))
    assert not any(t == "except E" for _, t, _ in flow(c))


def test_break_runs_its_own_finally_copy():
    inner = (
        Branch("if x", at(4), (Arm("True", (Break(at(5)),)),), "False"),
        Step("work()", at(6)),
    )
    loop = Loop(
        "for x in xs",
        at(2),
        "next",
        "done",
        (try_stmt(3, inner, finalbody=(Step("cleanup()", at(8)),)),),
        (),
    )
    c = chart((loop, Step("after()", at(9))))
    f = flow(c)
    assert {
        ("if x", "finally (break)", "True"),
        ("work()", "finally", None),
        ("finally (break)", "cleanup()", None),
        ("for x in xs", "after()", "done"),
    } <= f
    ids = {n.id for n in c.nodes}
    assert {"f#L3C4~finally", "f#L3C4~finally~break@L3C4", "f#L8C4~break@L3C4"} <= ids
    assert ("cleanup()", "after()", None) in f and ("cleanup()", "for x in xs", None) in f


def test_finally_continue_overrides_break():
    loop = Loop(
        "while True",
        at(2),
        "True",
        None,
        (try_stmt(3, (Break(at(4)),), finalbody=(Continue(at(6)),)),),
        (),
    )
    f = flow(chart((loop, Step("after()", at(7)))))
    assert ("finally (break)", "while True", None) in f
    assert not any(t == "after()" for _, t, _ in f)


def test_stray_break_inside_try_finally_reports_the_break_line():
    body = (Try(at(2), (Break(at(3)),), (), (), (Step("cleanup()", at(5)),)),)
    with pytest.raises(StrayLoopTransfer) as e:
        chart(body)
    assert (e.value.kind, e.value.loc) == ("break", at(3))
