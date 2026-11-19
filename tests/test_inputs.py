import os
from pathlib import Path, PurePosixPath

import pytest
from conftest import present

from pyflowcharts.inputs import (
    EXPLORE_HINT,
    Input,
    collision_error,
    drop_duplicate_keys,
    expand,
)

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
    assert len(e.errors) == 1
    assert e.warnings == []


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
    walked = expand([tmp_path / "a", tmp_path / "b"], []).inputs
    assert "both map to 'x'" in present(collision_error(walked))
    explicit_and_walked = expand([tmp_path / "a/x.py", tmp_path / "b"], []).inputs
    assert "both map to 'x'" in present(collision_error(explicit_and_walked))
    msg = present(collision_error(expand([tmp_path / "pkg"], []).inputs))  # longer key first
    assert "maps to 'mod' and" in msg
    assert "share the directory 'mod'" in msg
    msg = present(collision_error(expand([tmp_path / "pkg/mod.py", tmp_path / "t"], []).inputs))
    assert "maps to 'mod' and" in msg
    assert "share the directory 'mod'" in msg  # shorter first
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


def test_reserved_key_collision(tmp_path):
    tree(tmp_path, "callgraph.py", "sub/callgraph.py")
    msg = collision_error(expand([tmp_path], []).inputs, reserved={"callgraph": "it is reserved"})
    path = tmp_path / "callgraph.py"
    assert msg == f"error: output name collision: {path} maps to 'callgraph'; it is reserved"
    assert collision_error(expand([tmp_path / "sub"], []).inputs) is None  # no reservation given


def test_collision_hint_is_configurable(tmp_path):
    a = Input(tmp_path / "a/x.py", PurePosixPath("x"), True)
    b = Input(tmp_path / "b/x.py", PurePosixPath("x"), True)
    assert present(collision_error([a, b], hint=EXPLORE_HINT)).endswith(EXPLORE_HINT)


def test_prefix_keys_allowed_when_requested(tmp_path):
    short = Input(tmp_path / "mod.py", PurePosixPath("mod"), True)
    long = Input(tmp_path / "mod/x.py", PurePosixPath("mod/x"), False)
    assert collision_error([short, long], allow_prefixes=True) is None
    assert collision_error([short, long]) is not None


def test_drop_duplicate_keys_keeps_first(tmp_path):
    a = Input(tmp_path / "a/x.py", PurePosixPath("x"), False)
    b = Input(tmp_path / "b/x.py", PurePosixPath("x"), False)
    kept, messages = drop_duplicate_keys([a, b])
    assert kept == [a]
    expected = (
        f"error: output name collision: {a.path} and {b.path} both map to 'x'; "
        f"{EXPLORE_HINT}; showing only {a.path}"
    )
    assert messages == [expected]


def inp(path: str, key: str) -> Input:
    return Input(Path(path), PurePosixPath(key), True)


CASE = "which differ only in case"
HINT = "run them separately with different --output directories"


def test_keys_differing_only_in_case_collide_when_folding():
    a, b = inp("A.py", "A"), inp("a.py", "a")
    assert collision_error([a, b]) is None  # exact comparison, as the explorer uses
    assert collision_error([a, b], fold_case=True) == (
        f"error: output name collision: A.py and a.py map to 'A' and 'a', {CASE}; {HINT}"
    )
    nested = [inp("d/x.py", "d/x"), inp("D/x.py", "D/x")]
    assert f"map to 'd/x' and 'D/x', {CASE}" in present(collision_error(nested, fold_case=True))


def test_exact_same_key_message_is_unchanged_when_folding():
    same = [inp("a/x.py", "x"), inp("b/x.py", "x")]
    assert collision_error(same, fold_case=True) == collision_error(same)


def test_case_only_prefix_collides_when_folding():
    # A.py's function foo writes A/foo.svg; a/foo.py's module chart writes a/foo.svg.
    inputs = [inp("A.py", "A"), inp("a/foo.py", "a/foo")]
    assert collision_error(inputs) is None
    assert collision_error(inputs, fold_case=True) == (
        "error: output name collision: A.py maps to 'A' and a/foo.py to 'a/foo', which would "
        f"share the directory 'A' (the names differ only in case); {HINT}"
    )
    assert collision_error(inputs, fold_case=True, allow_prefixes=True) is None


def test_case_only_reserved_key_collides_when_folding():
    inputs = [inp("CallGraph.py", "CallGraph")]
    reserved = {"callgraph": "it is reserved"}
    assert collision_error(inputs, reserved) is None
    assert collision_error(inputs, reserved, fold_case=True) == (
        "error: output name collision: CallGraph.py maps to 'CallGraph', which differs only "
        "in case from 'callgraph'; it is reserved"
    )


def test_case_folding_is_per_character():
    # As for function names in output.py: "ß" is not "ss", but "σ" and "ς" clash.
    assert collision_error([inp("ß.py", "ß"), inp("ss.py", "ss")], fold_case=True) is None
    assert collision_error([inp("σ.py", "σ"), inp("ς.py", "ς")], fold_case=True) is not None
