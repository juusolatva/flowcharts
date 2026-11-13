import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from pyflowcharts.explorer.workspace import (
    FunctionSpan,
    Skipped,
    Workspace,
    snapshot_json,
)
from pyflowcharts.ir import ChartOptions

unix_non_root = pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0,
    reason="needs POSIX permissions and a non-root user",
)

F = "def f():\n    pass\n"
G = "def g():\n    pass\n"


class FakeStop:
    """Stands in for ``threading.Event``: ``wait`` advances a fake clock, then runs a callback."""

    def __init__(self) -> None:
        self.now = 0.0
        self.waits = 0
        self.flag = False
        self.on_wait: Callable[[int], None] | None = None

    def clock(self) -> float:
        return self.now

    def wait(self, timeout: float | None = None) -> bool:
        self.waits += 1
        self.now += timeout or 0.0
        if self.on_wait is not None:
            self.on_wait(self.waits)
        return self.flag

    def is_set(self) -> bool:
        return self.flag

    def set(self) -> None:
        self.flag = True


def make(paths: list[Path], stop: FakeStop | None = None) -> Workspace:
    stop = stop or FakeStop()
    return Workspace(
        paths,
        [],
        ChartOptions(),
        clock=stop.clock,
        stop=stop,  # type: ignore[arg-type]
    )


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def bump(path: Path, text: str, n: int = 1) -> None:
    """Rewrite ``path`` so its (mtime, size) certainly differ from before."""
    path.write_text(text)
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + n * 1_000_000_000))


def test_initial_parse_builds_generation_one(tmp_path):
    m = write(tmp_path / "m.py", F)
    snap = make([m]).current()
    assert snap.generation == 1
    assert snap.entries[0].key == "m"
    assert snap.entries[0].functions == (FunctionSpan("f", 1, 2),)
    assert snap.entries[0].doc == 0
    assert len(snap.documents) == len(snap.results) == 1


def test_refresh_without_change_does_nothing(tmp_path):
    ws = make([write(tmp_path / "m.py", F)])
    assert ws.refresh() is False
    assert ws.current().generation == 1


def test_refresh_after_edit_bumps_generation(tmp_path):
    m = write(tmp_path / "m.py", F)
    ws = make([m])
    bump(m, F + G)
    assert ws.refresh() is True
    snap = ws.current()
    assert snap.generation == 2
    assert [f.qualname for f in snap.entries[0].functions] == ["f", "g"]


def test_refresh_sees_new_and_deleted_files(tmp_path):
    write(tmp_path / "a.py", F)
    ws = make([tmp_path])
    assert len(ws.current().entries) == 1
    b = write(tmp_path / "b.py", G)
    assert ws.refresh() is True
    assert [e.key for e in ws.current().entries] == ["a", "b"]
    b.unlink()
    assert ws.refresh() is True
    assert [e.key for e in ws.current().entries] == ["a"]


def test_settle_waits_for_two_equal_fingerprints(tmp_path):
    m = write(tmp_path / "m.py", F)
    stop = FakeStop()
    ws = make([m], stop)
    bump(m, F + G)  # first change, seen by refresh()
    stop.on_wait = lambda n: bump(m, F + G + "def h():\n    pass\n", 2) if n == 1 else None
    assert ws.refresh() is True
    assert stop.waits == 2
    assert [f.qualname for f in ws.current().entries[0].functions] == ["f", "g", "h"]


def test_settle_gives_up_after_cap(tmp_path):
    m = write(tmp_path / "m.py", F)
    stop = FakeStop()
    ws = make([m], stop)
    bump(m, F + G)
    stop.on_wait = lambda n: bump(m, F + G + "x = 1\n" * n, n + 2)
    assert ws.refresh() is True
    assert stop.now >= Workspace.SETTLE_CAP
    assert stop.waits < 20
    assert ws.current().generation == 2


def test_stat_oserror_gives_sentinel(tmp_path, monkeypatch):
    m = write(tmp_path / "m.py", F)
    ws = make([m])
    real = Path.stat

    def stat(self, *args, **kwargs):
        if self.name == "m.py" and sys._getframe(1).f_code.co_name == "_stat":
            raise PermissionError("denied")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    assert ws.refresh() is True  # the sentinel differs from the real stat, and nothing raises
    assert ws.current().generation == 2


@unix_non_root
def test_fixing_directory_permissions_triggers_refresh(tmp_path):
    write(tmp_path / "ok.py", F)
    sub = tmp_path / "sub"
    write(sub / "inner.py", G)
    sub.chmod(0o000)
    try:
        ws = make([tmp_path])
        assert any("cannot read directory" in m for m in ws.current().messages)
        sub.chmod(0o755)
        assert ws.refresh() is True
        snap = ws.current()
        assert "sub/inner" in [e.key for e in snap.entries]
        assert not any("cannot read directory" in m for m in snap.messages)
    finally:
        sub.chmod(0o755)


def test_stop_ends_settle_immediately(tmp_path):
    m = write(tmp_path / "m.py", F)
    stop = FakeStop()
    ws = make([m], stop)
    stop.set()
    bump(m, F + G)
    assert ws.refresh() is False
    assert ws.current().generation == 1
    assert stop.waits == 1


def test_real_event_is_accepted_and_default_stop_works(tmp_path):
    m = write(tmp_path / "m.py", F)
    event = threading.Event()
    event.set()
    ws = Workspace([m], [], ChartOptions(), stop=event)
    bump(m, F + G)
    assert ws.refresh() is False
    assert Workspace([m], [], ChartOptions()).current().generation == 1


def test_runtime_duplicate_key_is_dropped(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write(a / "x.py", F)
    write(b / "y.py", G)
    ws = make([a, b])
    assert [e.key for e in ws.current().entries] == ["x", "y"]
    write(b / "x.py", G)
    assert ws.refresh() is True
    snap = ws.current()
    assert [e.key for e in snap.entries] == ["x", "y"]
    assert snap.entries[0].source == str(a / "x.py")
    assert any("showing only" in m for m in snap.messages)


def test_undecodable_file_becomes_error_entry(tmp_path):
    m = tmp_path / "m.py"
    m.write_bytes(b"\x00")
    ws = make([m])
    entry = ws.current().entries[0]
    assert entry.doc is None
    assert entry.error is not None
    assert "null bytes" in entry.error
    assert entry.empty is False
    assert entry.functions == ()
    assert entry.error in ws.current().messages


def test_skipped_module_chart_listed(tmp_path):
    m = write(tmp_path / "m.py", "break\nprint(1)\n")
    entry = make([m]).current().entries[0]
    assert entry.skipped == (
        Skipped("<module>", 1, "syntax error in module code; module chart skipped"),
    )
    assert entry.has_module is False
    assert entry.empty is False


def test_nothing_to_chart_only_for_explicit_files(tmp_path):
    pkg = tmp_path / "pkg"
    write(pkg / "__init__.py", "")
    ws = make([pkg])
    snap = ws.current()
    assert snap.entries[0].empty is True
    assert not any("nothing to chart" in m for m in snap.messages)

    explicit = write(tmp_path / "e.py", "")
    snap = make([explicit]).current()
    assert snap.entries[0].empty is True
    assert f"warning: {explicit}: nothing to chart" in snap.messages


def test_startup_failed_rules(tmp_path):
    assert make([tmp_path / "nope.py"]).startup_failed() is True
    js = write(tmp_path / "x.js", "var a;\n")
    assert make([js]).startup_failed() is True
    empty = tmp_path / "empty"
    empty.mkdir()
    ws = make([empty])
    assert ws.current().messages  # the "no source files found" warning
    assert ws.startup_failed() is False
    good = write(tmp_path / "good.py", F)
    ws = make([good, tmp_path / "missing.py"])
    assert ws.startup_failed() is False
    assert ws.startup_messages() == [f"{tmp_path / 'missing.py'}: error: no such file"]


def test_snapshot_json_shape(tmp_path):
    write(tmp_path / "a.py", "import b\n\n\ndef f():\n    b.g()\n")
    write(tmp_path / "b.py", G)
    snap = make([tmp_path]).current()
    data = snapshot_json(snap)
    assert data["generation"] == 1
    assert data["edges"] == [[[0, "f"], [1, "g"]]]
    assert data["messages"] == []
    assert list(data["entries"][0]) == [
        "key",
        "source",
        "doc",
        "module_name",
        "functions",
        "has_module",
        "skipped",
        "error",
        "empty",
    ]
    assert data["entries"][0]["functions"] == [{"qualname": "f", "line": 4, "end_line": 5}]
    assert data["entries"][1]["module_name"] == "b"


def test_failed_build_is_retried_without_further_changes(tmp_path, monkeypatch):
    m = write(tmp_path / "m.py", F)
    ws = make([m])
    bump(m, F + G)
    real = Workspace._build
    calls = []

    def flaky(self, generation, scan):
        calls.append(generation)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real(self, generation, scan)

    monkeypatch.setattr(Workspace, "_build", flaky)
    with pytest.raises(RuntimeError):
        ws.refresh()
    assert ws.current().generation == 1
    assert ws.refresh() is True
    assert ws.current().generation == 2
    assert [f.qualname for f in ws.current().entries[0].functions] == ["f", "g"]


def test_same_size_edit_with_restored_mtime_triggers_refresh(tmp_path):
    m = write(tmp_path / "m.py", F)
    ws = make([m])
    before = m.stat()
    time.sleep(0.05)  # the inode change time has a coarse clock on some file systems
    m.write_text(F.replace("def f", "def h"))
    os.utime(m, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert m.stat().st_size == before.st_size
    assert ws.refresh() is True
    assert [f.qualname for f in ws.current().entries[0].functions] == ["h"]
