import shutil
import subprocess

import pytest

from pyflowcharts.backends.dot_runner import DotFailed, DotNotFound, run_dot

needs_dot = pytest.mark.skipif(shutil.which("dot") is None, reason="Graphviz not installed")


@needs_dot
def test_renders_with_graphviz():
    assert b"<svg" in run_dot("digraph { a -> b }", "svg", timeout=30)


def fake_run(monkeypatch, outcome):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_passes_the_source_format_and_timeout(monkeypatch):
    calls = fake_run(monkeypatch, subprocess.CompletedProcess([], 0, b"<svg/>", b""))
    assert run_dot("digraph { é }", "png", dot="custom-dot", timeout=7) == b"<svg/>"
    ((args, kwargs),) = calls
    assert args == ["custom-dot", "-Tpng"]
    assert kwargs["input"] == "digraph { é }".encode()
    assert kwargs["timeout"] == 7


def test_missing_executable(monkeypatch):
    fake_run(monkeypatch, FileNotFoundError(2, "No such file or directory"))
    with pytest.raises(DotNotFound):
        run_dot("digraph {}", "svg", timeout=30)


def test_other_start_failure_is_a_failed_render(monkeypatch):
    fake_run(monkeypatch, PermissionError(13, "Permission denied"))
    with pytest.raises(DotFailed, match="could not be run: Permission denied"):
        run_dot("digraph {}", "svg", timeout=30)


def test_timeout(monkeypatch):
    fake_run(monkeypatch, subprocess.TimeoutExpired("dot", 5))
    with pytest.raises(DotFailed, match="took longer than 5 s"):
        run_dot("digraph {}", "svg", timeout=5)


def test_non_zero_exit_reports_graphviz_message(monkeypatch):
    fake_run(monkeypatch, subprocess.CompletedProcess([], 1, b"", b"Error: syntax error\n"))
    with pytest.raises(DotFailed, match="^Error: syntax error$"):
        run_dot("digraph {", "svg", timeout=30)


def test_non_zero_exit_without_message(monkeypatch):
    fake_run(monkeypatch, subprocess.CompletedProcess([], -9, b"", b""))
    with pytest.raises(DotFailed, match="dot exited with status -9"):
        run_dot("digraph {}", "svg", timeout=30)
