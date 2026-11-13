import ast
import textwrap

import pytest
from conftest import assert_graph_integrity, flow

from pyflowcharts.frontends.python import PythonFrontend
from pyflowcharts.ir import ChartOptions


def parse(text, **opts):
    return PythonFrontend().parse(textwrap.dedent(text).encode(), "t.py", ChartOptions(**opts))


@pytest.mark.parametrize(
    "src",
    [
        '"""doc"""\nimport os\nfrom a import b\nfrom __future__ import annotations\n',
        "def f(): pass\n@d\ndef g(): pass\nclass A: pass\n",
        "x = 1\ny += 2\nz: int = 3\nlogger = getLogger(__name__)\ntype T = int\n",
        "pass\n...\nglobal q\n",
        "",
    ],
)
def test_no_module_chart_for_declarations(src):
    assert parse(src).document.module is None


@pytest.mark.parametrize(
    "src",
    [
        "if __name__ == '__main__':\n    main()\n",
        "for x in y:\n    pass\n",
        "try:\n    import a\nexcept ImportError:\n    a = None\n",
        "with o:\n    pass\n",
        "assert x\n",
        "del x\n",
        "raise SystemExit\n",
        "main()\n",
        "match x:\n    case 1:\n        pass\n",
    ],
)
def test_module_chart_when_top_level_does_work(src):
    assert parse(src).document.module is not None


def test_main_block_flow():
    src = 'import sys\ndef main(): pass\nif __name__ == "__main__":\n    main()\n'
    m = parse(src).document.module
    cond = 'if __name__ == "__main__"'
    assert flow(m) == {
        ("module t", "import sys", None),
        ("import sys", "def main()", None),
        ("def main()", cond, None),
        (cond, "main()", "True"),
        (cond, "end", "False"),
        ("main()", "end", None),
    }
    assert m.qualname == "<module>"
    assert all(n.id.startswith("<module>#") for n in m.nodes)
    assert_graph_integrity(m)


def test_module_location_spans_first_statement_to_last_token():
    m = parse("\n\nmain()\nother()\n# c\n").document.module
    assert (m.location.line, m.location.end_line) == (3, 4)
    m = parse("#!/usr/bin/env python3\n# head\n\nmain()\n").document.module
    assert (m.location.line, m.location.column, m.location.end_line) == (4, 0, 4)


def test_assignment_with_comment_inside_is_not_work():
    assert parse("x = (  # c\n    1)\ny = \\\n    2\n").document.module is None


def test_no_module_option():
    r = parse("main()\nbreak\n", show_module=False)
    assert r.document.module is None and r.warnings == ()


def test_skeleton_syntax_error_means_no_module_chart():
    r = parse("main()\nx = = 1\ndef g(): pass\n")
    assert r.document.module is None and [c.qualname for c in r.document.functions] == ["g"]
    assert [(w.line, w.qualname) for w in r.warnings] == [(2, None)]


def test_stray_break_skips_module_chart():
    r = parse("main()\nbreak\ndef g(): pass\n")
    assert r.document.module is None and [c.qualname for c in r.document.functions] == ["g"]
    assert [str(w) for w in r.warnings] == [
        "t.py:2: warning: syntax error in module code; module chart skipped"
    ]
    assert r.warnings[0].qualname == "<module>"


def _needs_pep696(src: str) -> None:
    try:
        ast.parse(src)
    except SyntaxError:
        pytest.skip("this interpreter does not accept PEP 696 defaults")


def test_unsupported_top_level_syntax_skips_module_chart():
    src = "type Box[T = int] = list[T]\nmain()\ndef g(): pass\n"
    _needs_pep696(src)
    r = parse(src)
    assert r.document.module is None and [c.qualname for c in r.document.functions] == ["g"]
    assert [str(w) for w in r.warnings] == [
        "t.py:1: warning: unsupported syntax in module code; module chart skipped"
    ]
    assert r.warnings[0].qualname == "<module>"


def test_unsupported_syntax_without_top_level_work_is_quiet():
    # No module chart would be drawn, so the misread syntax changes nothing: no warning.
    src = "class A[T = int]:\n    def m(self):\n        return 1\ntype Box[T = int] = list[T]\n"
    _needs_pep696(src)
    r = parse(src)
    assert r.document.module is None and r.warnings == ()
    assert [c.qualname for c in r.document.functions] == ["A.m"]
