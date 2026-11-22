import os
import stat
from pathlib import PurePosixPath

import graphviz
import pytest

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
    assert w.graphviz_missing
    assert len(capsys.readouterr().err.splitlines()) == 1


def test_unwritable_directory_reported_once(tmp_path, capsys):
    blocker = tmp_path / "out"
    blocker.write_text("not a directory")
    w = Writer(blocker, ["json", "mermaid"])
    w.write(parse("def f(): pass\ndef g(): pass\nmain()\n"), PurePosixPath("m"))
    assert w.write_failed
    assert capsys.readouterr().err.count("cannot write") == 1


def test_write_callgraph(tmp_path):
    docs = link([parse_as("def f():\n    f()\n", "a")])
    Writer(tmp_path, ["json", "dot", "mermaid"]).write_callgraph(docs)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["callgraph.dot", "callgraph.mmd"]


def test_no_callgraph_without_charts(tmp_path):
    Writer(tmp_path / "o", ["dot"]).write_callgraph([parse_as("", "a")])
    assert not (tmp_path / "o").exists()


def test_function_names_differing_only_in_case_warn(tmp_path, capsys):
    doc = parse("def Foo(): pass\ndef foo(): pass\ndef FOO(): pass\ndef bar(): pass\n")
    Writer(tmp_path, ["dot"]).write(doc, PurePosixPath("t"))
    assert capsys.readouterr().err == (
        "warning: t.py: functions 'Foo', 'foo' and 'FOO' differ only in case; their files "
        "overwrite each other on case-insensitive file systems\n"
    )
    assert files(tmp_path) == {"t/Foo.dot", "t/foo.dot", "t/FOO.dot", "t/bar.dot"}


def test_case_clash_quiet_without_function_files(tmp_path, capsys):
    doc = parse("def Foo(): pass\ndef foo(): pass\n")
    Writer(tmp_path, ["json"]).write(doc, PurePosixPath("t"))
    assert capsys.readouterr().err == ""


def test_full_case_folding_is_not_a_clash(tmp_path, capsys):
    # File systems map case per character: "ß" and "ss" stay distinct.
    doc = parse("def ß(): pass\ndef ss(): pass\n")
    Writer(tmp_path, ["dot"]).write(doc, PurePosixPath("t"))
    assert capsys.readouterr().err == ""


def test_final_sigma_clashes_with_sigma(tmp_path, capsys):
    # Both upper-case to "Σ" under the per-character mapping file systems use.
    doc = parse("def σ(): pass\ndef ς(): pass\n")
    Writer(tmp_path, ["dot"]).write(doc, PurePosixPath("t"))
    assert "functions 'σ' and 'ς' differ only in case" in capsys.readouterr().err


def link_or_skip(link, target, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as err:  # Windows without the symlink privilege
        pytest.skip(f"cannot create symlinks: {err}")


def test_symlinked_output_directory_is_refused(tmp_path, capsys):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link_or_skip(tmp_path / "out", elsewhere, directory=True)
    w = Writer(tmp_path / "out", ["json", "mermaid"])
    w.write(parse("def f(): pass\nmain()\n"), PurePosixPath("m"))
    w.write_callgraph([parse_as("def g(): pass\n", "n")])
    assert w.write_failed
    assert list(elsewhere.iterdir()) == []
    err = capsys.readouterr().err
    assert err.count("symbolic link") == 1, err
    assert str(tmp_path / "out") in err


def test_symlinked_subdirectory_is_refused_and_the_rest_written(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link_or_skip(out / "pkg", elsewhere, directory=True)
    w = Writer(out, ["json", "mermaid"])
    w.write(parse("def f(): pass\nmain()\n"), PurePosixPath("pkg/m"))
    w.write(parse("def f(): pass\n"), PurePosixPath("pkg/n"))
    w.write(parse("def f(): pass\n"), PurePosixPath("top"))
    assert w.write_failed
    assert list(elsewhere.iterdir()) == []
    assert capsys.readouterr().err.count("symbolic link") == 1
    assert files(out) == {"top.json", "top/f.mmd"}


def test_symlinked_output_file_is_replaced_not_followed(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    out = tmp_path / "out"
    out.mkdir()
    link_or_skip(out / "m.json", victim)
    w = Writer(out, ["json"])
    w.write(parse("def f(): pass\n"), PurePosixPath("m"))
    assert not w.write_failed
    assert victim.read_text() == "precious"
    assert not (out / "m.json").is_symlink()
    assert '"functions"' in (out / "m.json").read_text()


def test_hard_linked_output_file_is_replaced_not_overwritten(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    out = tmp_path / "out"
    out.mkdir()
    try:
        (out / "m.json").hardlink_to(victim)
    except OSError as err:
        pytest.skip(f"cannot create hard links: {err}")
    Writer(out, ["json"]).write(parse("def f(): pass\n"), PurePosixPath("m"))
    assert victim.read_text() == "precious"
    assert '"functions"' in (out / "m.json").read_text()


def test_failed_write_leaves_neither_partial_nor_temporary_file(tmp_path, monkeypatch, capsys):
    (tmp_path / "m.json").write_text("old")

    def fail(*args):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("pyflowcharts.output.os.replace", fail)
    w = Writer(tmp_path, ["json"])
    w.write(parse("def f(): pass\n"), PurePosixPath("m"))
    assert w.write_failed
    assert "No space left on device" in capsys.readouterr().err
    assert files(tmp_path) == {"m.json"}
    assert (tmp_path / "m.json").read_text() == "old"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_new_files_get_the_usual_permissions(tmp_path):
    previous = os.umask(0o027)
    try:
        Writer(tmp_path, ["json"]).write(parse("def f(): pass\n"), PurePosixPath("m"))
    finally:
        os.umask(previous)
    assert stat.S_IMODE((tmp_path / "m.json").stat().st_mode) == 0o640


@pytest.mark.parametrize("key", [".", "..", "../m", "a/../../m", "/abs/m"])
def test_keys_outside_the_output_directory_are_rejected(tmp_path, key):
    with pytest.raises(ValueError, match="output key"):
        Writer(tmp_path / "out", ["json"]).write(parse("def f(): pass\n"), PurePosixPath(key))
    assert not (tmp_path / "out").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_rewritten_file_keeps_its_permissions(tmp_path):
    (tmp_path / "m.json").write_text("old")
    (tmp_path / "m.json").chmod(0o600)
    previous = os.umask(0o022)
    try:
        Writer(tmp_path, ["json"]).write(parse("def f(): pass\n"), PurePosixPath("m"))
    finally:
        os.umask(previous)
    assert stat.S_IMODE((tmp_path / "m.json").stat().st_mode) == 0o600
    assert '"functions"' in (tmp_path / "m.json").read_text()


def test_long_output_names_still_fit(tmp_path):
    # 245 bytes with ".json": within the usual 255-byte name limit, with no room for a
    # temporary name built from it.
    key = "f" * 240
    w = Writer(tmp_path, ["json"])
    w.write(parse("def f(): pass\n"), PurePosixPath(key))
    assert not w.write_failed
    assert files(tmp_path) == {f"{key}.json"}


def test_failed_cleanup_does_not_hide_the_write_error(tmp_path, monkeypatch, capsys):
    def fail_replace(*args):
        raise OSError(28, "No space left on device")

    def fail_unlink(self, missing_ok=False):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("pyflowcharts.output.os.replace", fail_replace)
    monkeypatch.setattr("pyflowcharts.output.Path.unlink", fail_unlink)
    w = Writer(tmp_path, ["json"])
    w.write(parse("def f(): pass\n"), PurePosixPath("m"))
    assert w.write_failed
    assert "No space left on device" in capsys.readouterr().err
