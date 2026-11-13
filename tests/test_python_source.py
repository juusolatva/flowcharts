import pytest

from pyflowcharts.frontends.base import SourceError
from pyflowcharts.frontends.python.source import Source


def src(text: str | bytes) -> Source:
    return Source.from_bytes(text if isinstance(text, bytes) else text.encode(), "t.py")


def first_stmt(text):
    """The first statement of the first function's body, with its source."""
    s = src(text)
    return s, s.tree.root_node.children[0].child_by_field_name("body").children[0]


def test_coding_cookie_and_bom():
    assert src(b"# -*- coding: latin-1 -*-\nx = '\xe9'\n").text.endswith("x = 'é'\n")
    s = src(b"\xef\xbb\xbfdef f():\n    pass\n")
    assert s.text.startswith("def f")
    assert s.location(s.tree.root_node.children[0]).column == 0


def test_crlf_is_normalised():
    s = src(b"def f():\r\n    g()\r\n")
    assert "\r" not in s.text
    assert s.location(s.tree.root_node.children[0]).end_line == 2


def test_bad_sources_are_file_level_errors():
    for raw in (b"# coding: nope\nx = 1\n", b"x = 1\x00\n", b"\xff\xfe\n"):
        with pytest.raises(SourceError):
            src(raw)


def test_source_text_joins_wrapped_code():
    s, node = first_stmt("def f():\n    g(\n        1,  # note\n        0x2)\n")
    assert s.source_text(node) == "g(1, 0x2)"
    s, node = first_stmt("def f():\n    (df\n     .filter()\n     .select())\n")
    assert s.source_text(node) == "(df.filter().select())"
    s, node = first_stmt("def f():\n    x = 1 + \\\n        2\n")
    assert s.source_text(node) == "x = 1 + 2"


def test_strings_are_verbatim():
    s, node = first_stmt('def f():\n    g(f"{ x }", """a\n  b""")\n')
    assert s.source_text(node) == 'g(f"{ x }", """a\n  b""")'


def test_locations_use_byte_columns_and_skip_trailing_comments():
    s = src("def f():\n    s = 'é'; g()\n    # trailing\n")
    func = s.tree.root_node.children[0]
    g = func.child_by_field_name("body").children[-2]
    assert (s.location(g).line, s.location(g).column) == (2, 14)
    assert s.location(func).end_line == 2


def test_many_live_trees_with_long_identifiers():
    """tree-sitter 0.26.0 corrupted node positions (and crashed) in this situation."""
    keep = []
    for n in (10, 100, 255, 256, 300, 1000):
        s = src(f"def {'f' * n}(): pass\ndef g(): pass\n")
        keep.append(s)
        assert s.location(s.tree.root_node.children[0]).end_column == n + 12


def test_single_line_spacing_is_kept_as_written():
    s = src("def f(x: tuple[int, ...] = .5):\n    from . import m\n")
    func = s.tree.root_node.children[0]
    assert s.source_text(func.child_by_field_name("parameters")) == "(x: tuple[int, ...] = .5)"
    assert s.source_text(func.child_by_field_name("body").children[0]) == "from . import m"
