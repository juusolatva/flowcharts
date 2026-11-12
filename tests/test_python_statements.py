import textwrap

import pytest
from conftest import flow

from pyflowcharts.cfg.builder import build_chart
from pyflowcharts.frontends.python.source import Source
from pyflowcharts.frontends.python.statements import convert_body, signature_label
from pyflowcharts.ir import ChartOptions, FunctionChart


def chart(text: str, **opts) -> FunctionChart:
    src = Source.from_bytes(textwrap.dedent(text).encode(), "t.py")
    func = next(n for n in _walk(src.tree.root_node) if n.type == "function_definition")
    options = ChartOptions(**opts)
    loc = src.location(func)
    body = convert_body(func, src, options)
    nodes, edges = build_chart("f", signature_label(func, src, options), loc, body, options)
    return FunctionChart("f", "f", False, [], None, loc, nodes, edges)


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


def labels(c: FunctionChart) -> set[str]:
    return {n.label for n in c.nodes}


def test_docstring_variants():
    assert flow(chart("def f():\n    'a' 'b'\n")) == {("def f()", "end", None)}
    assert "f'x'" in labels(chart("def f():\n    f'x'\n"))
    assert "'late'" in labels(chart("def f():\n    g()\n    'late'\n"))


def test_assignment_hidden_unless_right_side_calls():
    c = chart("def f():\n    x[g()] = 1\n    y = h()\n    z: int\n    a = b = k()\n")
    assert labels(c) == {"def f()", "end", "y = h()", "a = b = k()"}


def test_two_statements_on_one_line_get_distinct_ids():
    c = chart("def f():\n    x = g(); y = h()\n")
    assert {n.id for n in c.nodes} >= {"f#L2C4", "f#L2C13"}


def test_if_elif_located_at_elif():
    c = chart("def f(x):\n    if x:\n        a()\n    elif x > 1:\n        b()\n")
    assert next(n.id for n in c.nodes if n.label == "if x > 1") == "f#L4C4"
    assert ("if x > 1", "end", "False") in flow(c)


@pytest.mark.parametrize(
    "case,irrefutable",
    [
        ("case y:", True),
        ("case (y):", True),
        ("case _:", True),
        ("case Foo.bar:", False),
        ("case y if g:", False),
        ("case [a]:", False),
        ("case 1, 2:", False),
    ],
)
def test_match_irrefutable_last_case(case, irrefutable):
    src = f"def f(x):\n    match x:\n        case 0:\n            a()\n        {case}\n            b()\n"
    f = flow(chart(src))
    assert (("match x", "end", "no match") in f) is (not irrefutable)
    assert any(lbl == case[:-1] for _, _, lbl in f)


@pytest.mark.parametrize(
    "cond,exits",
    [
        ("True", False),
        ("1.0", False),
        ('"x"', False),
        ('b"x"', False),
        ("(1)", False),
        ("...", False),
        ("0.0", True),
        ('""', True),
        ("(1,)", True),
        ("n > 0", True),
    ],
)
def test_while_constant_conditions(cond, exits):
    f = flow(chart(f"def f(n):\n    while {cond}:\n        g()\n    after()\n"))
    assert ((f"while {cond}", "after()", "False") in f) is exits


def test_handler_labels_from_source():
    c = chart(
        "def f():\n    try:\n        a()\n    except (A, B) as e:\n        b()\n"
        "    except* C:\n        c()\n    except:\n        d()\n"
    )
    assert {"except (A, B) as e", "except* C", "except"} <= labels(c)


def test_with_keeps_parentheses_and_async():
    c = chart("def f(p):\n    with (open(p) as fh, lock):\n        a()\n")
    assert "with (open(p) as fh, lock)" in labels(c)
    assert "async with x" in labels(chart("async def f(x):\n    async with x:\n        a()\n"))


def test_return_labels():
    assert "return" in labels(chart("def f():\n    return\n"))
    assert "return" in labels(chart("def f():\n    return 1\n", show_returns=False))
    assert "return {'k': 1_000}" in labels(chart("def f():\n    return {'k': 1_000}\n"))


def test_nested_definitions_are_steps_located_at_def():
    c = chart(
        "def f():\n    @deco\n    def g(a, b=1) -> int:\n        pass\n    class C:\n        pass\n"
    )
    assert {"def g(a, b=1) -> int", "class C"} <= labels(c)
    assert next(n.id for n in c.nodes if n.label.startswith("def g")) == "f#L3C4"


def test_signature_label_keeps_source_spacing():
    c = chart(
        "def f(a: int, /, b=2, *args, c, d: str = 'x', **kw) -> bool: ...", max_label_length=200
    )
    assert c.nodes[0].label == "def f(a: int, /, b=2, *args, c, d: str = 'x', **kw) -> bool"
    hidden = chart("async def f(a):\n    pass\n", show_parameters=False)
    assert hidden.nodes[0].label == "async def f(...)"


def test_chained_assignment_looks_only_at_the_final_value():
    c = chart("def f():\n    a[g()] = b[h()] = v\n    x = y = k()\n")
    assert labels(c) == {"def f()", "end", "x = y = k()"}


def test_type_call_target_is_an_assignment_not_a_type_alias():
    c = chart("def f(m):\n    type(m).a = v\n    type(m).b = g()\n    type Alias = list[int]\n")
    assert labels(c) == {"def f(m)", "end", "type(m).b = g()", "type Alias = list[int]"}


def test_multiline_case_pattern_label():
    src = "def f(x):\n    match x:\n        case (\n            A\n            | B\n        ):\n            a()\n"
    assert ("match x", "a()", "case (A | B)") in flow(chart(src))


def test_while_constant_check_does_not_leak_syntax_warnings():
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        c = chart('def f():\n    while "\\d":\n        g()\n')
    assert ('while "\\d"', "end", "False") not in flow(c)
