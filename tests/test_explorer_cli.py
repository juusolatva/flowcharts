import _thread
import argparse
import importlib
import shutil
import socket
import sys
import threading
from pathlib import Path

import pytest

from pyflowcharts import cli_options
from pyflowcharts.cli import main
from pyflowcharts.explorer import main as explore
from pyflowcharts.explorer.main import port
from pyflowcharts.explorer.server import ExplorerServer
from pyflowcharts.inputs import EXPLORE_HINT
from pyflowcharts.output import GRAPHVIZ_NOT_FOUND

explorer_main = importlib.import_module("pyflowcharts.explorer.main")
needs_dot = pytest.mark.skipif(shutil.which("dot") is None, reason="Graphviz not installed")


def write(directory: Path, name: str, text: str = "def f():\n    pass\n") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def run(args, **kwargs):
    return explore([*args, "--no-browser"], serve_forever=False, **kwargs)


def test_explore_dispatch_from_sys_argv(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["pyflowcharts", "explore", "--help"])
    with pytest.raises(SystemExit) as info:
        main(None)
    assert info.value.code == 0
    assert "--port" in capsys.readouterr().out


def test_bare_cli_unchanged():
    with pytest.raises(SystemExit) as info:
        main([])
    assert info.value.code == 2


def test_dot_slash_explore_is_a_file(tmp_path, monkeypatch, capsys):
    write(tmp_path, "explore", "x = 1\n")
    monkeypatch.chdir(tmp_path)
    assert main(["./explore", "-o", str(tmp_path / "out")]) == 1
    assert "unsupported file type" in capsys.readouterr().err


def test_help_mentions_explore(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "pyflowcharts explore PATH" in capsys.readouterr().out


def test_port_bounds():
    assert port("0") == 0
    assert port("65535") == 65535
    for bad in ("-1", "65536", "x"):
        with pytest.raises(argparse.ArgumentTypeError):
            port(bad)


@needs_dot
def test_no_browser_prints_url(tmp_path, capsys):
    opened = []
    src = write(tmp_path, "m.py")
    assert explore([str(src), "--no-browser"], open_browser=opened.append, serve_forever=False) == 0
    out = capsys.readouterr().out
    assert out.startswith("pyflowcharts explorer: http://127.0.0.1:")
    assert "/?token=" in out
    assert opened == []


@needs_dot
def test_opens_browser_by_default(tmp_path, capsys):
    opened = []
    src = write(tmp_path, "m.py")
    assert explore([str(src)], open_browser=opened.append, serve_forever=False) == 0
    url = capsys.readouterr().out.strip().removeprefix("pyflowcharts explorer: ")
    assert opened == [url]


@needs_dot
def test_startup_fails_when_nothing_parses(tmp_path, capsys):
    assert run([str(tmp_path / "nope.py")]) == 1
    assert "nope.py" in capsys.readouterr().err
    other = write(tmp_path, "x.js", "var a;\n")
    assert run([str(other)]) == 1
    assert "unsupported file type" in capsys.readouterr().err


@needs_dot
def test_empty_directory_starts(tmp_path, capsys):
    (tmp_path / "d").mkdir()
    assert run([str(tmp_path / "d")]) == 0
    assert "no source files found" in capsys.readouterr().err


@needs_dot
def test_key_collision_exits_1(tmp_path, capsys):
    a = write(tmp_path / "a", "x.py")
    b = write(tmp_path / "b", "x.py")
    assert run([str(a), str(b)]) == 1
    assert capsys.readouterr().err.endswith(EXPLORE_HINT + "\n")


def test_graphviz_missing_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert run([str(write(tmp_path, "m.py"))]) == 2
    assert capsys.readouterr().err == GRAPHVIZ_NOT_FOUND + "\n"


@needs_dot
def test_port_in_use_exits_1(tmp_path, capsys):
    src = write(tmp_path, "m.py")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        assert run([str(src), "--port", str(sock.getsockname()[1])]) == 1
    assert capsys.readouterr().err.startswith("error: cannot listen on")


def test_chart_options_shared(monkeypatch):
    for parse in (
        lambda: main(["m.py", "--max-label", "0"]),
        lambda: run(["m.py", "--max-label", "0"]),
    ):
        with pytest.raises(SystemExit) as info:
            parse()
        assert info.value.code == 2
    parser = argparse.ArgumentParser()
    cli_options.add_chart_options(parser)
    args = parser.parse_args(["--max-label", "7", "--no-module"])
    options = cli_options.chart_options(args)
    assert options.max_label_length == 7
    assert not options.show_module


@needs_dot
def test_serving_path_stops_on_interrupt(tmp_path, monkeypatch):
    src = write(tmp_path, "m.py")
    real_serve = ExplorerServer.serve_forever
    real_watch = explorer_main.watch
    watchers: list[threading.Thread] = []

    def serve(self, *args, **kwargs):
        # Interrupt the real loop, so the stdlib's own cleanup still runs.
        timer = threading.Timer(0.3, _thread.interrupt_main)
        timer.start()
        try:
            return real_serve(self, *args, **kwargs)
        finally:
            timer.cancel()

    def watch(*args, **kwargs):
        watchers.append(threading.current_thread())
        return real_watch(*args, **kwargs)

    monkeypatch.setattr(ExplorerServer, "serve_forever", serve)
    monkeypatch.setattr(explorer_main, "watch", watch)
    before = set(threading.enumerate())
    assert explore([str(src), "--no-browser"]) == 0
    assert len(watchers) == 1
    watchers[0].join(timeout=5)
    assert not watchers[0].is_alive()
    assert set(threading.enumerate()) <= before


@needs_dot
def test_expand_oserror_exits_1(tmp_path, monkeypatch, capsys):
    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(explorer_main, "expand", denied)
    assert run([str(write(tmp_path, "m.py"))]) == 1
    assert capsys.readouterr().err == "error: denied\n"


@needs_dot
def test_first_parse_oserror_exits_1(tmp_path, monkeypatch, capsys):
    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(explorer_main, "Workspace", denied)
    assert run([str(write(tmp_path, "m.py"))]) == 1
    assert capsys.readouterr().err == "error: denied\n"
