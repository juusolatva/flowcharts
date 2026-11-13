import shutil
import sys

import pytest

from pyflowcharts.explorer.render import RenderError, svg
from pyflowcharts.output import GRAPHVIZ_MISSING, GRAPHVIZ_NOT_FOUND

needs_dot = pytest.mark.skipif(shutil.which("dot") is None, reason="Graphviz not installed")


@needs_dot
def test_svg_renders_dot_source():
    assert b"<title>a#start</title>" in svg('digraph g { "a#start" -> "a#end" }')


@pytest.mark.skipif(sys.platform == "win32", reason="needs a shell script")
def test_svg_timeout_reports_the_configured_limit(tmp_path):
    slow = tmp_path / "slowdot"
    slow.write_text("#!/bin/sh\nsleep 5\n")
    slow.chmod(0o755)
    with pytest.raises(RenderError, match=r"longer than 0\.2 s"):
        svg("digraph {}", timeout=0.2, dot=str(slow))


@needs_dot
def test_svg_syntax_error_raises_render_error():
    with pytest.raises(RenderError):
        svg("digraph {")


def test_missing_executable_raises_render_error(tmp_path):
    with pytest.raises(RenderError, match="could not be run"):
        svg("digraph {}", dot=str(tmp_path / "no-such-dot"))


@pytest.mark.skipif(sys.platform == "win32", reason="needs a shell script")
def test_silent_failure_reports_exit_status(tmp_path):
    bad = tmp_path / "baddot"
    bad.write_text("#!/bin/sh\nexit 3\n")
    bad.chmod(0o755)
    with pytest.raises(RenderError, match="status 3"):
        svg("digraph {}", dot=str(bad))


def test_graphviz_missing_text_unchanged():
    assert GRAPHVIZ_MISSING == GRAPHVIZ_NOT_FOUND + " or use --format json dot mermaid"


def test_oserror_without_strerror_still_explains(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr("pyflowcharts.explorer.render.subprocess.run", boom)
    with pytest.raises(RenderError, match="could not be run: boom"):
        svg("digraph {}")
