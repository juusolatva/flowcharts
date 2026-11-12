import ast
import textwrap

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
    assert list(v.skipped) == ["f"] and v.skipped["f"].line == line and v.outside is None
    assert v.skipped["f"].message == "syntax error in 'f'; function skipped"


def test_indented_method_line_mapping_and_eof_without_newline():
    v = check("class A:\n    def m(self):\n        x = = 1\n    def n(self):\n        return 1")
    assert v.skipped["A.m"].line == 3 and "A.n" not in v.skipped


def test_nested_function_errors_stay_nested():
    v = check("def outer():\n    def inner():\n    return 1\n")  # empty nested body
    assert list(v.skipped) == ["outer.inner"] and v.skipped["outer.inner"].line == 2
    v = check("def outer():\n    x = 1\n    def inner():\n        nonlocal x\n        x = 2\n")
    assert v == Validation({}, None)
    v = check("def outer():\n    def inner():\n        x = 1\n      y = 2\n    return 1\n")
    assert list(v.skipped) == ["outer"]  # under-indent belongs to outer


def test_outside_errors():
    v = check("x = = 1\nclass A:\n    y = = 2\n    def m(self):\n        z = = 3\n")
    assert list(v.skipped) == ["A.m"] and v.outside is not None and v.outside.line == 1
    assert v.outside.message == "syntax error outside functions; nearby code may be missing"
    v = check("@(\ndef f():\n    pass\n")
    assert v.skipped == {} and v.outside is not None  # decorator error; f itself is fine
    v = check("def f()\n    pass\n\ndef g():\n    pass\n")
    assert v.skipped == {} and v.outside is not None and v.outside.line == 1


def test_tree_sitter_only_errors_and_version_skew():
    v = check("def f(:\n    pass\n")
    assert v.skipped["f"].line == 1 and v.outside is None
    try:
        ast.parse("try:\n    pass\nexcept A, B:\n    pass\n")
    except SyntaxError:  # tree-sitter accepts this PEP 758 form; this interpreter does not
        v = check("def f():\n    try:\n        pass\n    except A, B:\n        pass\n")
        assert list(v.skipped) == ["f"] and v.skipped["f"].line == 4


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
    assert list(v.skipped) == ["f"] and v.outside is None
    assert v.skipped["f"].message == "unsupported syntax in 'f'; function skipped"
