import textwrap

import pytest

from pyflowcharts.frontends.base import SourceError
from pyflowcharts.frontends.python import PythonFrontend
from pyflowcharts.ir import ChartOptions


def parse(text, **opts):
    return PythonFrontend().parse(textwrap.dedent(text).encode(), "t.py", ChartOptions(**opts))


def test_broken_neighbour_is_skipped_and_others_charted():
    r = parse(
        "def good():\n    return 1\n\ndef broken(:\n    pass\n\ndef also_good():\n    return 2\n"
    )
    assert [c.qualname for c in r.document.functions] == ["good", "also_good"]
    assert [(w.line, w.qualname) for w in r.warnings] == [(4, "broken")]
    assert str(r.warnings[0]) == "t.py:4: warning: syntax error in 'broken'; function skipped"


def test_nested_error_keeps_outer_chart():
    r = parse("def outer():\n    def inner():\n        x = = 1\n    return 1\n")
    assert [c.qualname for c in r.document.functions] == ["outer"]
    assert "def inner()" in {n.label for n in r.document.functions[0].nodes}


def test_break_outside_loop_is_a_skipped_function():
    r = parse("def f(xs):\n    for x in xs:\n        def g():\n            break\n    return 1\n")
    assert [c.qualname for c in r.document.functions] == ["f"]
    assert [(w.line, w.qualname) for w in r.warnings] == [(4, "f.g")]
    r = parse("def f():\n    continue\n")
    assert r.document.functions == []
    assert r.warnings[0].line == 2


def test_outside_error_is_one_warning_without_qualname():
    r = parse("x = = 1\ndef g():\n    pass\n")
    assert [c.qualname for c in r.document.functions] == ["g"]
    assert [(w.line, w.qualname) for w in r.warnings] == [(1, None)]
    r = parse("@(\ndef f():\n    pass\n")  # decorator error: f is still charted
    assert [c.qualname for c in r.document.functions] == ["f"]
    assert len(r.warnings) == 1


def test_metadata_is_complete_and_option_independent():
    src = 'def f(a: list[int] = "a  b") -> dict[str, int]:\n    pass\n'
    for n in (5, 60, 200):
        (c,) = parse(src, max_label_length=n).document.functions
        assert c.parameters[0].default == '"a  b"'
        assert c.returns == "dict[str, int]"


def test_document_metadata_and_locations():
    raw = b"# -*- coding: latin-1 -*-\ndef f():\n    print('\xe9')\n    # trailing\n"
    r = PythonFrontend().parse(raw, "t.py", ChartOptions())
    c = r.document.functions[0]
    assert (r.document.language, r.document.schema_version) == ("python", 3)
    assert c.nodes[2].label == "print('é')"
    assert c.location.end_line == 3
    assert c.is_async is False
    assert c.name == "f"


def test_too_deeply_nested_is_a_source_error():
    deep = "+".join(["1"] * 20000)
    with pytest.raises(SourceError, match="too deeply nested"):
        parse(f"def f():\n    x = {deep}\n")
