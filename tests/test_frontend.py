import textwrap
from pathlib import Path

import pytest
from conftest import chart_of, flow

from pyflowcharts.frontends import SourceError, UnsupportedLanguageError, frontend_for_path
from pyflowcharts.frontends.base import Diagnostic, ParseResult
from pyflowcharts.frontends.python_ast import PythonFrontend
from pyflowcharts.ir import ChartOptions, NodeKind, Parameter, ParamKind


def test_sequential_body_and_implicit_end():
    c = chart_of("""
        def f(a, b=1):
            print(a)
            g(b)
    """)
    assert flow(c) == {
        ("def f(a, b=1)", "print(a)", None),
        ("print(a)", "g(b)", None),
        ("g(b)", "end", None),
    }
    assert c.nodes[0].id == "f#start" and c.nodes[0].kind is NodeKind.START


def test_return_and_raise_end_the_path():
    c = chart_of("""
        def f(x):
            log(x)
            return x + 1
    """)
    assert ("return x + 1", "end", None) in flow(c)
    r = chart_of("def f():\n    raise ValueError('no')\n")
    assert flow(r) == {
        ("def f()", "raise ValueError('no')", None),
        ("raise ValueError('no')", "end", None),
    }
    assert r.nodes[-1].kind is NodeKind.RAISE


def test_signature_recorded():
    c = chart_of(
        "def f(a: int, /, b=2, *args, c, d: str = 'x', **kw) -> bool: ...",
        max_label_length=200,
    )
    P, K = Parameter, ParamKind
    assert c.parameters == [
        P("a", "int", None, K.POSITIONAL_ONLY),
        P("b", None, "2", K.POSITIONAL_OR_KEYWORD),
        P("args", None, None, K.VAR_POSITIONAL),
        P("c", None, None, K.KEYWORD_ONLY),
        P("d", "str", "'x'", K.KEYWORD_ONLY),
        P("kw", None, None, K.VAR_KEYWORD),
    ]
    assert c.returns == "bool"
    assert c.nodes[0].label == "def f(a: int, /, b=2, *args, c, d: str='x', **kw) -> bool"


VARS = """
    def f(xs):
        n = 0
        total = sum(xs)
        n += 1
        return total
"""


def test_variables_hidden_unless_call():
    labels = {n.label for n in chart_of(VARS).nodes}
    assert "total = sum(xs)" in labels and not {"n = 0", "n += 1"} & labels


def test_variables_shown_with_option():
    assert {"n = 0", "n += 1"} <= {n.label for n in chart_of(VARS, show_variables=True).nodes}


def test_hidden_parameters_and_returns():
    labels = {n.label for n in chart_of(VARS, show_parameters=False, show_returns=False).nodes}
    assert {"def f(...)", "return"} <= labels


def test_qualnames_and_duplicates():
    doc = (
        PythonFrontend()
        .parse(
            textwrap.dedent("""
            def top(): pass
            class A:
                def m(self):
                    def inner(): pass
                @property
                def x(self): return 1
                @x.setter
                def x(self, v): pass
            async def co(): pass
        """).encode(),
            "t.py",
            ChartOptions(),
        )
        .document
    )
    assert [c.qualname for c in doc.functions] == ["top", "A.m", "A.m.inner", "A.x", "A.x@L9", "co"]
    co = doc.functions[-1]
    assert co.is_async and co.nodes[0].label == "async def co()"
    assert doc.functions[4].nodes[0].id == "A.x@L9#start"


def test_empty_bodies():
    for body in ['"""doc"""', "...", "pass"]:
        assert flow(chart_of(f"def f():\n    {body}\n")) == {("def f()", "end", None)}


def test_unreachable_code_kept():
    c = chart_of("def f():\n    return 1\n    print('dead')\n")
    dead = next(n for n in c.nodes if n.label == "print('dead')")
    assert all(e.target != dead.id for e in c.edges)
    assert ("return 1", "end", None) in flow(c)


def test_long_labels_truncated():
    c = chart_of(f"def f():\n    g({'a' * 100})\n", max_label_length=20)
    assert c.nodes[2].label == "g(" + "a" * 17 + "…"  # nodes[0]=start, nodes[1]=end


def test_source_errors():
    with pytest.raises(SourceError) as e:
        PythonFrontend().parse(b"def f(:\n", "bad.py", ChartOptions())
    assert e.value.line == 1 and str(e.value).startswith("bad.py:1: error:")
    with pytest.raises(SourceError):
        PythonFrontend().parse(b"x = 1\x00\n", "nul.py", ChartOptions())


def test_compiler_only_syntax_errors():  # ast.parse accepts these; compile() must reject them
    cases = [
        (b"def f():\n    break\n", 2),
        (b"def f():\n    continue\n", 2),
        (b"def f():\n    x = 1\n    nonlocal x\n", 3),
    ]
    for src, line in cases:
        with pytest.raises(SourceError) as e:
            PythonFrontend().parse(src, "loop.py", ChartOptions())
        assert e.value.line == line


def test_coding_cookie():
    src = b"# -*- coding: latin-1 -*-\ndef f():\n    print('\xe9')\n"
    doc = PythonFrontend().parse(src, "l1.py", ChartOptions()).document
    assert doc.functions[0].nodes[2].label == "print('é')"


def test_registry():
    assert isinstance(frontend_for_path(Path("x.PY")), PythonFrontend)
    with pytest.raises(UnsupportedLanguageError):
        frontend_for_path(Path("x.js"))


def test_document_metadata():
    doc = PythonFrontend().parse(b"", "empty.py", ChartOptions()).document
    assert (doc.source, doc.language, doc.functions, doc.schema_version) == (
        "empty.py",
        "python",
        [],
        1,
    )


def test_too_deeply_nested_source_is_a_source_error():
    deep = "+".join(["1"] * 20000)  # ast.parse itself overflows
    with pytest.raises(SourceError, match="too deeply nested"):
        PythonFrontend().parse(f"x = {deep}\n".encode(), "deep.py", ChartOptions())
    medium = "+".join(["1"] * 3000)  # parses, but charting (ast.unparse) overflows
    src = f"def f():\n    g(\n{medium})\n"  # multi-line, so the label falls back to ast.unparse
    with pytest.raises(SourceError, match="too deeply nested"):
        PythonFrontend().parse(src.encode(), "deep.py", ChartOptions())


SOURCE_TEXT = """
def f(x):
    if x == 0xD800:
        g("double", 'single')
    for i in range(0b11):
        print(f"{i!r}", "é")
    with open("p") as fh, lock:
        g(fh)
    match x:
        case 0x1 | "a":
            g()
    raise ValueError("bad")  # trailing comment
    return {"k": 1_000}
"""


def test_labels_keep_source_text():
    c = chart_of(SOURCE_TEXT)
    labels = {n.label for n in c.nodes}
    assert {
        "if x == 0xD800",
        "g(\"double\", 'single')",
        "for i in range(0b11)",
        'print(f"{i!r}", "é")',
        'with open("p") as fh, lock',
        'raise ValueError("bad")',
        'return {"k": 1_000}',
    } <= labels
    assert 'case 0x1 | "a"' in {e.label for e in c.edges}


def test_multiline_labels_fall_back_to_unparse():
    c = chart_of("def f():\n    g(1,  # note\n      0x2)\n")
    assert "g(1, 2)" in {n.label for n in c.nodes}


def test_block_of_only_hidden_assignments_is_shown():
    c = chart_of("""
        def f(memo, xs):
            if memo is None:
                memo = {}
            for x in xs:
                total += x
            return memo
    """)
    assert {
        ("if memo is None", "memo = {}", "True"),
        ("memo = {}", "for x in xs", None),
        ("if memo is None", "for x in xs", "False"),
        ("for x in xs", "total += x", "next"),
        ("total += x", "for x in xs", None),
    } <= flow(c)


def test_reveal_applies_per_block():
    c = chart_of("""
        def f(a):
            if a:
                n = 0
                g()
            else:
                n = 1
    """)
    labels = {n.label for n in c.nodes}
    assert "n = 1" in labels and "n = 0" not in labels


def test_function_body_of_only_assignments_is_shown():
    c = chart_of("def f(self):\n    self.x = 1\n    self.y = 2\n")
    assert {("self.x = 1", "self.y = 2", None), ("self.y = 2", "end", None)} <= flow(c)


def test_diagnostic_renders_like_errors():
    assert str(Diagnostic("a.py", 3, "boom", "f")) == "a.py:3: warning: boom"
    assert str(Diagnostic("a.py", None, "boom", None)) == "a.py: warning: boom"


def test_parse_returns_result_without_warnings():
    result = PythonFrontend().parse(b"def f(): pass\n", "t.py", ChartOptions())
    assert isinstance(result, ParseResult) and result.warnings == ()
