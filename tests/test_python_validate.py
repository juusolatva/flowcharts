import ast
import textwrap
import time

import pytest

from pyflowcharts.frontends.python.discovery import find_functions
from pyflowcharts.frontends.python.source import Source
from pyflowcharts.frontends.python.validate import Validation, validate


def check(text: str) -> Validation:
    s = Source.from_bytes(textwrap.dedent(text).encode(), "t.py")
    return validate(s, find_functions(s.tree.root_node), "t.py")


def test_clean_file():
    assert check("def f():\n    return 1\n") == Validation({}, None)


@pytest.mark.parametrize(
    "body,line",
    [
        ("", 1),
        ("    try:\n        x()\n", 3),
        ("    x()\n      y()\n", 3),
        ("    if x:\n", 2),
        ("    for a in b:\n", 2),
        ("    with a:\n", 2),
        ("    try:\n        x()\n    except:\n", 4),
    ],
)
def test_invalid_python_tree_sitter_accepts(body, line):
    v = check(f"def f():\n{body}\n\ndef g():\n    pass\n")
    assert list(v.skipped) == ["f"]
    assert v.skipped["f"].line == line
    assert v.outside is None
    assert v.skipped["f"].message == "syntax error in 'f'; function skipped"


def test_indented_method_line_mapping_and_eof_without_newline():
    v = check("class A:\n    def m(self):\n        x = = 1\n    def n(self):\n        return 1")
    assert v.skipped["A.m"].line == 3
    assert "A.n" not in v.skipped


def test_nested_function_errors_stay_nested():
    v = check("def outer():\n    def inner():\n    return 1\n")  # empty nested body
    assert list(v.skipped) == ["outer.inner"]
    assert v.skipped["outer.inner"].line == 2
    v = check("def outer():\n    x = 1\n    def inner():\n        nonlocal x\n        x = 2\n")
    assert v == Validation({}, None)
    v = check("def outer():\n    def inner():\n        x = 1\n      y = 2\n    return 1\n")
    assert list(v.skipped) == ["outer"]  # under-indent belongs to outer


def test_outside_errors():
    v = check("x = = 1\nclass A:\n    y = = 2\n    def m(self):\n        z = = 3\n")
    assert list(v.skipped) == ["A.m"]
    assert v.outside is not None
    assert v.outside.line == 1
    assert v.outside.message == "syntax error outside functions; nearby code may be missing"
    v = check("@(\ndef f():\n    pass\n")
    assert v.skipped == {}
    assert v.outside is not None  # decorator error; f itself is fine
    v = check("def f()\n    pass\n\ndef g():\n    pass\n")
    assert v.skipped == {}
    assert v.outside is not None
    assert v.outside.line == 1


def test_tree_sitter_only_errors_and_version_skew():
    v = check("def f(:\n    pass\n")
    assert v.skipped["f"].line == 1
    assert v.outside is None
    try:
        ast.parse("try:\n    pass\nexcept A, B:\n    pass\n")
    except SyntaxError:  # tree-sitter accepts this PEP 758 form; this interpreter does not
        v = check("def f():\n    try:\n        pass\n    except A, B:\n        pass\n")
        assert list(v.skipped) == ["f"]
        assert v.skipped["f"].line == 4


def test_ast_syntax_warnings_are_neither_printed_nor_fatal(capsys):
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # a leaked SyntaxWarning would become a SyntaxError
        v = check('def f(s):\n    return re.match("\\d", s)\n')
    assert v == Validation({}, None)
    assert capsys.readouterr().err == ""


def test_grammar_only_rejection_is_reported_as_unsupported_syntax():
    src = "def f[T = int](x: T) -> T:\n    return x\n\ndef g():\n    pass\n"
    try:
        ast.parse(src)
    except SyntaxError:
        pytest.skip("this interpreter does not accept PEP 696 defaults")
    v = check(src)
    assert list(v.skipped) == ["f"]
    assert v.outside is None
    assert v.skipped["f"].message == "unsupported syntax in 'f'; function skipped"


def test_non_ascii_text_around_nested_functions():
    # Stubs are placed by UTF-8 byte offsets, so multi-byte characters must not shift them.
    v = check(
        "def outer():\n    s = 'é漢'; t = 1\n    def inner():\n        return s\n    x = = 1\n"
    )
    assert list(v.skipped) == ["outer"]
    assert v.skipped["outer"].line == 5
    v = check("def outer():\n    s = 'é漢'\n    def inner():\n        y = = 2\n    return s\n")
    assert list(v.skipped) == ["outer.inner"]
    assert v.skipped["outer.inner"].line == 4


def test_each_level_of_nesting_is_checked_on_its_own():
    text = (
        "class A:\n"
        "    def m(self):\n"
        "        def a():\n"
        "            async def b():\n"
        "                z = = 3\n"
        "            return b\n"
        "        @deco\n"
        "        def c():\n"
        "            return 1\n"
        "        y = = 2\n"
        "x = 1\n"
    )
    v = check(text)
    assert {name: d.line for name, d in v.skipped.items()} == {"A.m.a.b": 5, "A.m": 10}
    assert v.outside is None


def test_recovery_from_one_syntax_error_stays_linear():
    # Each function used to be checked against a stubbed copy of the whole file: 20,000
    # short functions took about 50 s. Now about 1 s; the bound leaves room for slow runners.
    text = "".join(f"def f{i}():\n    return {i}\n\n" for i in range(20_000)) + "def bad(:\n"
    s = Source.from_bytes(text.encode(), "t.py")
    functions = find_functions(s.tree.root_node)
    started = time.perf_counter()
    v = validate(s, functions, "t.py")
    assert time.perf_counter() - started < 10
    assert list(v.skipped) == ["bad"]
