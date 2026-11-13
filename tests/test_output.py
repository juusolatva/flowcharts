from pathlib import PurePosixPath

import graphviz

from pyflowcharts.calls import link
from pyflowcharts.frontends.python import PythonFrontend
from pyflowcharts.ir import ChartOptions
from pyflowcharts.output import Writer


def parse(text: str):
    return PythonFrontend().parse(text.encode(), "t.py", ChartOptions()).document


def parse_as(text: str, key: str):
    options = ChartOptions()
    return PythonFrontend().parse(text.encode(), f"{key}.py", options, PurePosixPath(key)).document


def files(root):
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_mirrored_key_with_module_and_functions(tmp_path):
    doc = parse("def f(): pass\nmain()\n")
    Writer(tmp_path, ["json", "dot", "mermaid"]).write(doc, PurePosixPath("pkg/io/load"))
    assert files(tmp_path) == {
        "pkg/io/load.json",
        "pkg/io/load.dot",
        "pkg/io/load.mmd",
        "pkg/io/load/f.dot",
        "pkg/io/load/f.mmd",
    }


def test_module_only_creates_no_function_directory(tmp_path):
    Writer(tmp_path, ["dot"]).write(parse("main()\n"), PurePosixPath("s"))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["s.dot"]


def test_no_outputs_creates_no_directories(tmp_path):
    Writer(tmp_path / "o", ["dot"]).write(parse(""), PurePosixPath("pkg/__init__"))
    assert not (tmp_path / "o").exists()


def test_dotted_stem_keeps_full_name(tmp_path):  # Review Focus 2
    doc = parse("def f(): pass\nmain()\n")
    Writer(tmp_path, ["json", "dot"]).write(doc, PurePosixPath("a.b"))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.b", "a.b.dot", "a.b.json"]


def test_missing_graphviz_reported_once_for_module_and_functions(tmp_path, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise graphviz.ExecutableNotFound(["dot"])

    monkeypatch.setattr("pyflowcharts.output.render", boom)
    w = Writer(tmp_path, ["svg"])
    w.write(parse("def f(): pass\nmain()\n"), PurePosixPath("m"))
    assert w.graphviz_missing and len(capsys.readouterr().err.splitlines()) == 1


def test_unwritable_directory_reported_once(tmp_path, capsys):
    blocker = tmp_path / "out"
    blocker.write_text("not a directory")
    w = Writer(blocker, ["json", "mermaid"])
    w.write(parse("def f(): pass\ndef g(): pass\nmain()\n"), PurePosixPath("m"))
    assert w.write_failed and capsys.readouterr().err.count("cannot write") == 1


def test_write_callgraph(tmp_path):
    docs = link([parse_as("def f():\n    f()\n", "a")])
    Writer(tmp_path, ["json", "dot", "mermaid"]).write_callgraph(docs)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["callgraph.dot", "callgraph.mmd"]


def test_no_callgraph_without_charts(tmp_path):
    Writer(tmp_path / "o", ["dot"]).write_callgraph([parse_as("", "a")])
    assert not (tmp_path / "o").exists()
