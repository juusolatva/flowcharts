import shutil
from pathlib import Path

import graphviz
import pytest

from pyflowcharts.cli import main
from pyflowcharts.frontends.python import PythonFrontend
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
    assert f"{bad}:1: warning:" in capsys.readouterr().err
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

    monkeypatch.setattr("pyflowcharts.output.render", boom)
    src = write(tmp_path, "m.py", "def f(): pass\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "svg", "json"]) == 2
    assert "Graphviz" in capsys.readouterr().err and (tmp_path / "o/m.json").exists()


def test_nothing_to_chart_warns(tmp_path, capsys):
    src = write(tmp_path, "m.py", "X = 1\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json"]) == 0
    assert f"warning: {src}: nothing to chart" in capsys.readouterr().err
    assert from_json((tmp_path / "o/m.json").read_text()).functions == []


@needs_dot
def test_end_to_end_fixture(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "sample.py"
    formats = ["json", "dot", "svg", "png", "mermaid"]
    assert main([str(fixture), "-o", str(tmp_path), "-f", *formats]) == 0
    doc = from_json((tmp_path / "sample.json").read_text())
    assert (
        doc == PythonFrontend().parse(fixture.read_bytes(), str(fixture), ChartOptions()).document
    )
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


def test_unwritable_output_dir_is_an_error(tmp_path, capsys):
    src = write(tmp_path, "m.py", "def f(): pass\n")
    blocker = write(tmp_path, "out", "not a directory")
    assert main([str(src), "-o", str(blocker), "-f", "json", "mermaid"]) == 1
    assert "cannot write" in capsys.readouterr().err


def test_write_failure_does_not_stop_other_outputs(tmp_path, capsys):
    long_name = "f" * 300  # longer than typical file-name limits (255 bytes)
    src = write(tmp_path, "m.py", f"def {long_name}(): pass\ndef g(): pass\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "mermaid"]) == 1
    assert "cannot write" in capsys.readouterr().err
    assert (tmp_path / "o/m.json").exists() and (tmp_path / "o/m/g.mmd").exists()


BROKEN = "def good():\n    return 1\n\ndef broken(:\n    pass\n"


def test_skipped_function_warns_exits_1_and_writes_the_rest(tmp_path, capsys):
    src = write(tmp_path, "m.py", BROKEN)
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "mermaid"]) == 1
    expected = f"{src}:4: warning: syntax error in 'broken'; function skipped"
    assert expected in capsys.readouterr().err
    doc = from_json((tmp_path / "o/m.json").read_text())
    assert [c.qualname for c in doc.functions] == ["good"]
    assert (tmp_path / "o/m/good.mmd").exists()


def test_all_functions_skipped_writes_empty_json_without_nothing_to_chart(tmp_path, capsys):
    src = write(tmp_path, "m.py", "def broken(:\n    pass\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json"]) == 1
    err = capsys.readouterr().err
    assert "function skipped" in err and "nothing to chart" not in err
    assert from_json((tmp_path / "o/m.json").read_text()).functions == []


def test_function_selection_with_skipped_names(tmp_path, capsys):
    src = write(tmp_path, "m.py", BROKEN)
    assert main([str(src), "-o", str(tmp_path / "o1"), "-f", "json", "--function", "good"]) == 0
    assert capsys.readouterr().err == ""
    args = ["-o", str(tmp_path / "o2"), "-f", "json", "--function", "good", "broken"]
    assert main([str(src), *args]) == 1
    assert "function skipped" in capsys.readouterr().err
    doc = from_json((tmp_path / "o2/m.json").read_text())
    assert [c.qualname for c in doc.functions] == ["good"]
    assert main([str(src), "-o", str(tmp_path / "o3"), "--function", "zzz"]) == 1
    err = capsys.readouterr().err
    assert "available: good, broken (skipped)" in err and not (tmp_path / "o3").exists()


def test_outside_error_warns_even_with_function_filter(tmp_path, capsys):
    src = write(tmp_path, "m.py", "x = = 1\ndef good():\n    return 1\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "--function", "good"]) == 1
    assert "syntax error outside functions" in capsys.readouterr().err


def outputs(root):
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_directory_input_mirrors_tree(tmp_path):
    write(tmp_path / "src/pkg/io", "load.py", "def f(): pass\nmain()\n")
    write(tmp_path / "src/pkg", "__init__.py", "")
    assert main([str(tmp_path / "src"), "-o", str(tmp_path / "o"), "-f", "json", "dot"]) == 0
    assert outputs(tmp_path / "o") == {
        "pkg/__init__.json",
        "pkg/io/load.json",
        "pkg/io/load.dot",
        "pkg/io/load/f.dot",
        "callgraph.dot",
    }
    doc = from_json((tmp_path / "o/pkg/io/load.json").read_text())
    assert doc.source == str(tmp_path / "src/pkg/io/load.py") and doc.module.qualname == "<module>"


def test_walked_empty_file_does_not_warn(tmp_path, capsys):
    write(tmp_path / "d", "__init__.py", "")
    assert main([str(tmp_path / "d"), "-o", str(tmp_path / "o"), "-f", "json"]) == 0
    assert capsys.readouterr().err == ""


def test_explicit_file_also_walked_still_warns(tmp_path, capsys):
    empty = write(tmp_path / "d", "e.py", "")
    assert main([str(tmp_path / "d"), str(empty), "-o", str(tmp_path / "o"), "-f", "json"]) == 0
    assert f"warning: {empty}: nothing to chart" in capsys.readouterr().err


def test_empty_directory_warning(tmp_path, capsys):
    (tmp_path / "e").mkdir()
    assert main([str(tmp_path / "e"), "-o", str(tmp_path / "o")]) == 0
    assert "no source files found" in capsys.readouterr().err


def test_exclude_option(tmp_path):
    write(tmp_path / "s/venv", "v.py", "def v(): pass\n")
    write(tmp_path / "s", "a.py", "def a(): pass\n")
    args = ["-o", str(tmp_path / "o"), "-f", "json", "--exclude", "venv"]
    assert main([str(tmp_path / "s"), *args]) == 0
    assert sorted(p.name for p in (tmp_path / "o").iterdir()) == ["a.json"]


def test_exclude_rejects_bare_slash(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main([str(tmp_path), "--exclude", "/"])
    assert exc.value.code == 2


def test_prefix_collision_writes_nothing(tmp_path, capsys):
    write(tmp_path / "s", "mod.py", "def f(): pass\n")
    write(tmp_path / "s/mod", "__init__.py", "")
    assert main([str(tmp_path / "s"), "-o", str(tmp_path / "o")]) == 1
    assert "share the directory 'mod'" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


def test_no_module_option(tmp_path):
    src = write(tmp_path, "s.py", "def f(): pass\nmain()\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "--no-module"]) == 0
    assert from_json((tmp_path / "o/s.json").read_text()).module is None


def test_function_selects_module(tmp_path):
    src = write(tmp_path, "s.py", "def f(): pass\nmain()\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "--function", "<module>"]) == 0
    doc = from_json((tmp_path / "o/s.json").read_text())
    assert doc.functions == [] and doc.module is not None and doc.schema_version == 3
    assert main([str(src), "-o", str(tmp_path / "o2"), "-f", "json", "--function", "f"]) == 0
    assert from_json((tmp_path / "o2/s.json").read_text()).module is None


def test_skipped_module_and_function_filter(tmp_path, capsys):
    src = write(tmp_path, "s.py", "def good(): pass\nbreak\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "--function", "good"]) == 0
    assert "module chart skipped" not in capsys.readouterr().err
    args = ["-o", str(tmp_path / "o2"), "-f", "json", "--function", "<module>"]
    assert main([str(src), *args]) == 1
    assert "syntax error in module code; module chart skipped" in capsys.readouterr().err


def test_available_list_is_deduplicated(tmp_path, capsys):
    a = write(tmp_path / "a", "a.py", "def f(): pass\nmain()\n")
    b = write(tmp_path / "b", "b.py", "def f(): pass\nmain()\n")
    assert main([str(a), str(b), "-o", str(tmp_path / "o"), "--function", "zzz"]) == 1
    assert "available: f, <module>" in capsys.readouterr().err


def test_no_nothing_to_chart_after_function_filter(tmp_path, capsys):
    a = write(tmp_path, "a.py", "def foo(): pass\n")
    b = write(tmp_path, "b.py", "def bar(): pass\n")
    assert main([str(a), str(b), "-o", str(tmp_path / "o"), "-f", "json", "--function", "foo"]) == 0
    assert "nothing to chart" not in capsys.readouterr().err


def test_syntax_error_only_file_has_no_nothing_to_chart(tmp_path, capsys):
    src = write(tmp_path, "s.py", "x = = 1\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json"]) == 1
    err = capsys.readouterr().err
    assert "syntax error outside functions" in err and "nothing to chart" not in err


def test_json_has_module_name_from_walk(tmp_path):
    write(tmp_path / "src/pkg", "mod.py", "def f(): pass\n")
    assert main([str(tmp_path / "src"), "-o", str(tmp_path / "o"), "-f", "json"]) == 0
    assert from_json((tmp_path / "o/pkg/mod.json").read_text()).module_name == "pkg.mod"


def test_directory_run_writes_call_graph_with_cross_file_edge(tmp_path):
    write(tmp_path / "src/pkg", "__init__.py", "")
    write(tmp_path / "src/pkg", "lib.py", "def g(): pass\n")
    write(tmp_path / "src/pkg", "app.py", "from .lib import g\ndef f():\n    g()\n")
    assert main([str(tmp_path / "src"), "-o", str(tmp_path / "o"), "-f", "json", "dot"]) == 0
    dot = (tmp_path / "o/callgraph.dot").read_text()
    assert "label=pkg.app" in dot.replace('"', "") and "-> " in dot
    call = from_json((tmp_path / "o/pkg/app.json").read_text()).functions[0].calls[0]
    assert (call.target.module, call.target.qualname) == ("pkg.lib", "g")


def test_json_only_writes_no_call_graph(tmp_path):
    src = write(tmp_path, "m.py", "def f(): pass\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json"]) == 0
    assert not (tmp_path / "o/callgraph.dot").exists()


def test_no_call_graph_option(tmp_path):
    src = write(tmp_path, "m.py", "def f(): pass\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "dot", "--no-call-graph"]) == 0
    assert (tmp_path / "o/m/f.dot").exists()
    assert not (tmp_path / "o/callgraph.dot").exists()


def test_function_filter_limits_picture_but_not_targets(tmp_path):
    src = write(tmp_path, "m.py", "def g(): pass\ndef f():\n    g()\n")
    out = str(tmp_path / "o")
    assert main([str(src), "-o", out, "-f", "json", "dot", "--function", "f"]) == 0
    assert "0#g" not in (tmp_path / "o/callgraph.dot").read_text()
    call = from_json((tmp_path / "o/m.json").read_text()).functions[0].calls[0]
    assert call.target.qualname == "g"


def test_reserved_callgraph_key(tmp_path, capsys):
    src = write(tmp_path, "callgraph.py", "def f(): pass\n")
    assert main([str(src), "-o", str(tmp_path / "o")]) == 1
    err = capsys.readouterr().err
    assert "reserved for the call graph" in err and not (tmp_path / "o").exists()
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "--no-call-graph"]) == 0


def test_missing_graphviz_still_writes_text_call_graph(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise graphviz.ExecutableNotFound(["dot"])

    monkeypatch.setattr("pyflowcharts.output.render", boom)
    monkeypatch.setattr("pyflowcharts.output.render_callgraph", boom)
    src = write(tmp_path, "m.py", "def f(): pass\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "svg", "dot"]) == 2
    assert (tmp_path / "o/callgraph.dot").exists()
    assert len(capsys.readouterr().err.splitlines()) == 1  # reported once
