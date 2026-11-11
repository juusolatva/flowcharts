import shutil
from pathlib import Path

import graphviz
import pytest

from pyflowcharts.cli import main
from pyflowcharts.frontends.python_ast import PythonFrontend
from pyflowcharts.ir import ChartOptions
from pyflowcharts.serialize import from_json

needs_dot = pytest.mark.skipif(shutil.which("dot") is None, reason="Graphviz not installed")


def write(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


@needs_dot
def test_default_formats(tmp_path):
    src = write(tmp_path, "mod.py", "def f(x):\n    return x\n")
    assert main([str(src), "-o", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out/mod.json").exists() and (tmp_path / "out/mod/f.svg").exists()


def test_text_formats(tmp_path):
    src = write(tmp_path, "mod.py", "class A:\n    def m(self):\n        pass\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "dot", "mermaid"]) == 0
    assert {p.name for p in (tmp_path / "o/mod").iterdir()} == {"A.m.dot", "A.m.mmd"}
    assert (tmp_path / "o/mod.json").exists()


def test_options_reach_frontend(tmp_path):
    src = write(tmp_path, "m.py", "def f(a):\n    n = 1\n    return n\n")
    args = ["-f", "json", "--variables", "--no-parameters", "--no-returns"]
    assert main([str(src), "-o", str(tmp_path / "o"), *args]) == 0
    labels = {n.label for n in from_json((tmp_path / "o/m.json").read_text()).functions[0].nodes}
    assert {"n = 1", "def f(...)", "return"} <= labels


def test_max_label_option(tmp_path):
    src = write(tmp_path, "m.py", "def f():\n    g('a long argument here')\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "--max-label", "8"]) == 0
    labels = {n.label for n in from_json((tmp_path / "o/m.json").read_text()).functions[0].nodes}
    assert "g('a lo…" in labels


def test_function_filter_and_unknown(tmp_path, capsys):
    src = write(tmp_path, "m.py", "def a(): pass\ndef b(): pass\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "--function", "b"]) == 0
    assert [c.qualname for c in from_json((tmp_path / "o/m.json").read_text()).functions] == ["b"]
    assert main([str(src), "-o", str(tmp_path / "o2"), "--function", "zzz"]) == 1
    assert "available: a, b" in capsys.readouterr().err


def test_function_accepts_several_names(tmp_path):
    src = write(tmp_path, "m.py", "def a(): pass\ndef b(): pass\ndef c(): pass\n")
    for i, flags in enumerate([["--function", "a", "b"], ["--function", "a", "--function", "b"]]):
        out = tmp_path / f"o{i}"
        assert main([str(src), "-o", str(out), "-f", "json", *flags]) == 0
        assert [c.qualname for c in from_json((out / "m.json").read_text()).functions] == ["a", "b"]


def test_json_only_when_requested(tmp_path):
    src = write(tmp_path, "m.py", "def f(): pass\n")
    empty = write(tmp_path, "e.py", "X = 1\n")
    assert main([str(src), str(empty), "-o", str(tmp_path / "o"), "-f", "mermaid"]) == 0
    assert (tmp_path / "o/m/f.mmd").exists()
    assert not list((tmp_path / "o").glob("*.json"))


def test_bad_file_does_not_stop_others(tmp_path, capsys):
    bad = write(tmp_path, "bad.py", "def f(:\n")
    good = write(tmp_path, "good.py", "def g(): pass\n")
    assert main([str(bad), str(good), "-o", str(tmp_path / "o"), "-f", "json"]) == 1
    assert f"{bad}:1: error:" in capsys.readouterr().err
    assert (tmp_path / "o/good.json").exists()


def test_missing_and_unsupported_files(tmp_path, capsys):
    js = write(tmp_path, "x.js", "")
    assert main([str(tmp_path / "nope.py"), str(js), "-o", str(tmp_path / "o")]) == 1
    err = capsys.readouterr().err
    assert "no such file" in err and "unsupported file type" in err


def test_stem_collision(tmp_path, capsys):
    a = write(tmp_path / "a", "utils.py", "def f(): pass\n")
    b = write(tmp_path / "b", "utils.py", "def g(): pass\n")
    assert main([str(a), str(b), "-o", str(tmp_path / "o")]) == 1
    assert "collision" in capsys.readouterr().err and not (tmp_path / "o").exists()


def test_missing_graphviz(tmp_path, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise graphviz.ExecutableNotFound(["dot"])

    monkeypatch.setattr("pyflowcharts.cli.render", boom)
    src = write(tmp_path, "m.py", "def f(): pass\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "svg", "json"]) == 2
    assert "Graphviz" in capsys.readouterr().err and (tmp_path / "o/m.json").exists()


def test_no_functions_warns(tmp_path, capsys):
    src = write(tmp_path, "m.py", "X = 1\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json"]) == 0
    assert "no functions found" in capsys.readouterr().err
    assert from_json((tmp_path / "o/m.json").read_text()).functions == []


@needs_dot
def test_end_to_end_fixture(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "sample.py"
    formats = ["json", "dot", "svg", "png", "mermaid"]
    assert main([str(fixture), "-o", str(tmp_path), "-f", *formats]) == 0
    doc = from_json((tmp_path / "sample.json").read_text())
    assert doc == PythonFrontend().parse(fixture.read_bytes(), str(fixture), ChartOptions())
    for c in doc.functions:
        for ext in ("dot", "svg", "png", "mmd"):
            assert (tmp_path / "sample" / f"{c.qualname}.{ext}").stat().st_size > 0


def test_same_file_twice_is_not_a_collision(tmp_path):
    src = write(tmp_path, "m.py", "def f(): pass\n")
    assert (
        main([str(src), str(tmp_path / "." / "m.py"), "-o", str(tmp_path / "o"), "-f", "json"]) == 0
    )
    assert (tmp_path / "o/m.json").exists()


def test_max_label_must_be_positive(tmp_path, capsys):
    src = write(tmp_path, "m.py", "def f(): pass\n")
    with pytest.raises(SystemExit) as e:
        main([str(src), "--max-label", "0"])
    assert e.value.code == 2 and "positive integer" in capsys.readouterr().err
