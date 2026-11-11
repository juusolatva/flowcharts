from pyflowcharts.ir import ChartOptions, NodeKind
from pyflowcharts.labels import shorten


def test_shorten_collapses_whitespace():
    assert shorten("a =  1\n   + 2", 60) == "a = 1 + 2"


def test_shorten_truncates_with_ellipsis():
    assert shorten("x" * 70, 10) == "x" * 9 + "…"
    assert len(shorten("x" * 70, 10)) == 10


def test_shorten_keeps_exact_length():
    assert shorten("x" * 10, 10) == "x" * 10


def test_enum_values_are_strings():
    assert NodeKind.DECISION == "decision"


def test_default_options():
    assert ChartOptions() == ChartOptions(False, True, True, 60)
