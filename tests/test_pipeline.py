from pathlib import Path, PurePosixPath

from pyflowcharts.inputs import Input
from pyflowcharts.ir import ChartOptions
from pyflowcharts.pipeline import parse_all


def item(path: Path, key: str) -> Input:
    return Input(path, PurePosixPath(key), explicit=True)


def test_parse_all_links_across_files(tmp_path):
    (tmp_path / "a.py").write_text("from b import g\n\ndef f():\n    g()\n")
    (tmp_path / "b.py").write_text("def g():\n    pass\n")
    parsed = parse_all([item(tmp_path / "a.py", "a"), item(tmp_path / "b.py", "b")], ChartOptions())
    call = parsed.results[0][1].document.functions[0].calls[0]
    assert call.target is not None
    assert call.target.qualname == "g"
    assert parsed.read_errors == []
    assert parsed.errors == {}


def test_parse_all_collects_read_errors_without_printing(tmp_path, capsys):
    missing = tmp_path / "nope.py"
    parsed = parse_all([item(missing, "nope")], ChartOptions())
    assert parsed.results == []
    assert len(parsed.read_errors) == 1
    assert "no such file" in parsed.read_errors[0]
    assert parsed.errors == {missing: parsed.read_errors[0]}
    assert capsys.readouterr().err == ""


def test_parse_all_keeps_source_text(tmp_path):
    (tmp_path / "a.py").write_text("def f():\n    pass\n")
    parsed = parse_all([item(tmp_path / "a.py", "a")], ChartOptions())
    assert parsed.results[0][1].source_text == "def f():\n    pass\n"
