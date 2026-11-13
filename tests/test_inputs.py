import os
from pathlib import Path

import pytest

from pyflowcharts.inputs import collision_error, expand

needs_non_root = pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="root can read everything, and chmod(0) does not block reading on Windows",
)


def tree(root: Path, *relpaths: str) -> None:
    for rel in relpaths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n")


def keys(expansion) -> list[str]:
    return [i.key.as_posix() for i in expansion.inputs]


def test_walk_order_and_keys(tmp_path):
    tree(tmp_path, "z.py", "pkg/__init__.py", "pkg/io/load.py", "a.py", "notes.txt")
    assert keys(expand([tmp_path], [])) == ["a", "pkg/__init__", "pkg/io/load", "z"]
    assert all(not i.explicit for i in expand([tmp_path], []).inputs)


def test_hidden_pycache_and_dir_symlinks_skipped(tmp_path):
    tree(tmp_path, "src/.venv/x.py", "src/.h.py", "src/__pycache__/c.py", "src/ok.py", "other/o.py")
    (tmp_path / "src/link").symlink_to(tmp_path / "other", target_is_directory=True)
    (tmp_path / "src/broken.py").symlink_to(tmp_path / "missing.py")
    assert keys(expand([tmp_path / "src"], [])) == ["ok"]


def test_file_symlink_to_regular_file_is_charted(tmp_path):
    tree(tmp_path, "real/m.py", "src/a.py")
    (tmp_path / "src/l.py").symlink_to(tmp_path / "real/m.py")
    assert keys(expand([tmp_path / "src"], [])) == ["a", "l"]


def test_hidden_directory_argument_is_walked(tmp_path):
    tree(tmp_path, ".hidden/x.py")
    assert keys(expand([tmp_path / ".hidden"], [])) == ["x"]


def test_symlinked_directory_argument_is_walked(tmp_path):
    tree(tmp_path, "real/m.py")
    (tmp_path / "ln").symlink_to(tmp_path / "real", target_is_directory=True)
    assert keys(expand([tmp_path / "ln"], [])) == ["m"]


@needs_non_root
def test_unreadable_directory_is_an_error_and_walk_continues(tmp_path):
    tree(tmp_path, "locked/x.py", "ok.py")
    (tmp_path / "locked").chmod(0)
    try:
        e = expand([tmp_path], [])
    finally:
        (tmp_path / "locked").chmod(0o755)
    assert keys(e) == ["ok"]
    assert e.errors == [f"{tmp_path / 'locked'}: error: cannot read directory: Permission denied"]


@needs_non_root
def test_unreadable_directory_argument_gets_only_the_error(tmp_path):
    (tmp_path / "locked").mkdir()
    (tmp_path / "locked").chmod(0)
    try:
        e = expand([tmp_path / "locked"], [])
    finally:
        (tmp_path / "locked").chmod(0o755)
    assert len(e.errors) == 1 and e.warnings == []


def test_explicit_files_pass_through(tmp_path):
    e = expand([tmp_path / "nope.py", tmp_path / "x.js"], [])
    assert [(i.key.as_posix(), i.explicit) for i in e.inputs] == [("nope", True), ("x", True)]


@pytest.mark.parametrize(
    "patterns, expected",
    [
        (["venv"], ["a", "pkg/m", "pkg/sub/s", "x_pb2"]),
        (["*_pb2.py"], ["a", "pkg/m", "pkg/sub/s", "venv/v"]),
        (["pkg/*"], ["a", "venv/v", "x_pb2"]),
        (["pkg/"], ["a", "venv/v", "x_pb2"]),
        (["m.py/"], ["a", "pkg/m", "pkg/sub/s", "venv/v", "x_pb2"]),
        (["PKG"], ["a", "pkg/m", "pkg/sub/s", "venv/v", "x_pb2"]),
        (["pkg/sub/"], ["a", "pkg/m", "venv/v", "x_pb2"]),
    ],
)
def test_exclude(tmp_path, patterns, expected):
    tree(tmp_path, "a.py", "pkg/m.py", "pkg/sub/s.py", "venv/v.py", "x_pb2.py")
    assert keys(expand([tmp_path], patterns)) == expected


@needs_non_root
def test_excluded_directory_is_not_walked(tmp_path):
    # a walk into venv/ would hit onerror; pruning means no error
    tree(tmp_path, "venv/x.py", "a.py")
    (tmp_path / "venv").chmod(0)
    try:
        assert expand([tmp_path], ["venv/"]).errors == []
    finally:
        (tmp_path / "venv").chmod(0o755)


def test_exclude_does_not_apply_to_explicit_files(tmp_path):
    tree(tmp_path, "venv.py")
    assert keys(expand([tmp_path / "venv.py"], ["venv.py"])) == ["venv"]


def test_dedupe_keeps_first_and_ors_explicit(tmp_path):
    tree(tmp_path, "d/e.py")
    e = expand([tmp_path / "d", tmp_path / "d" / "e.py"], [])
    assert [(i.key.as_posix(), i.explicit) for i in e.inputs] == [("e", True)]


def test_empty_directory_warns_but_repeated_directory_does_not(tmp_path):
    (tmp_path / "empty").mkdir()
    tree(tmp_path, "d/x.py")
    assert expand([tmp_path / "empty"], []).warnings == [
        f"warning: {tmp_path / 'empty'}: no source files found"
    ]
    assert expand([tmp_path / "d", tmp_path / "d"], []).warnings == []


def test_collisions(tmp_path):
    tree(
        tmp_path,
        *("a/x.py", "b/x.py", "pkg/mod.py", "pkg/mod/__init__.py"),
        *("q/m.py", "q/m_extra.py", "t/mod/__init__.py"),
    )
    assert "both map to 'x'" in collision_error(expand([tmp_path / "a", tmp_path / "b"], []).inputs)
    explicit_and_walked = expand([tmp_path / "a/x.py", tmp_path / "b"], []).inputs
    assert "both map to 'x'" in collision_error(explicit_and_walked)
    msg = collision_error(expand([tmp_path / "pkg"], []).inputs)  # longer key first
    assert "maps to 'mod' and" in msg and "share the directory 'mod'" in msg
    msg = collision_error(expand([tmp_path / "pkg/mod.py", tmp_path / "t"], []).inputs)
    assert "maps to 'mod' and" in msg and "share the directory 'mod'" in msg  # shorter first
    assert collision_error(expand([tmp_path / "q"], []).inputs) is None


def test_dot_argument(tmp_path, monkeypatch):  # Review Focus 1
    tree(tmp_path, "pkg/m.py")
    monkeypatch.chdir(tmp_path)
    assert keys(expand([Path(".")], [])) == ["pkg/m"]


def test_upper_case_extension_in_walk(tmp_path):  # Review Focus 3
    tree(tmp_path, "X.PY")
    assert keys(expand([tmp_path], [])) == ["X"]


def test_argument_spellings_give_same_keys(tmp_path, monkeypatch):  # Review Focus 4
    tree(tmp_path, "src/p/m.py")
    monkeypatch.chdir(tmp_path)
    spellings = [Path("src"), Path("src/"), tmp_path / "src"]
    assert [keys(expand([p], [])) for p in spellings] == [["p/m"]] * 3


def test_outputs_inside_tree_are_not_inputs(tmp_path):  # Review Focus 5
    tree(tmp_path, "m.py", "charts/m.json", "charts/m.svg", "charts/m.dot", "charts/m.mmd")
    assert keys(expand([tmp_path], [])) == ["m"]
