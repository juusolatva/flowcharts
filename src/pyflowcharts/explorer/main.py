"""``pyflowcharts explore PATH…``: start the local explorer."""

from __future__ import annotations

import argparse
import secrets
import shutil
import sys
import threading
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path

from pyflowcharts import __version__
from pyflowcharts.cli_options import add_chart_options, chart_options
from pyflowcharts.explorer.server import ExplorerServer, shutdown, watch
from pyflowcharts.explorer.workspace import Workspace
from pyflowcharts.inputs import EXPLORE_HINT, collision_error, expand
from pyflowcharts.output import GRAPHVIZ_NOT_FOUND

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_GRAPHVIZ = 2


def port(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = -1
    if not 0 <= value <= 65535:
        raise argparse.ArgumentTypeError(f"must be a port from 0 to 65535, got {text!r}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyflowcharts explore",
        description="Browse the flowcharts of Python files in a local web app.",
        epilog="Put input paths before options that take several values (--exclude).",
    )
    parser.add_argument(
        "paths", nargs="+", type=Path, metavar="PATH", help="source files or directories"
    )
    add_chart_options(parser)
    parser.add_argument(
        "--port",
        type=port,
        default=0,
        metavar="N",
        help="port to listen on, 0 to 65535 (default: 0, a free port)",
    )
    parser.add_argument("--no-browser", action="store_true", help="only print the URL")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(
    argv: Sequence[str],
    *,
    open_browser: Callable[[str], object] = webbrowser.open,
    serve_forever: bool = True,
) -> int:
    args = _parser().parse_args(argv)
    if shutil.which("dot") is None:
        print(GRAPHVIZ_NOT_FOUND, file=sys.stderr)
        return EXIT_NO_GRAPHVIZ
    expansion = expand(args.paths, args.exclude)
    collision = collision_error(expansion.inputs, hint=EXPLORE_HINT, allow_prefixes=True)
    if collision is not None:
        print(collision, file=sys.stderr)
        return EXIT_ERROR

    stop = threading.Event()
    workspace = Workspace(args.paths, args.exclude, chart_options(args), stop=stop)
    for message in workspace.startup_messages():
        print(message, file=sys.stderr)
    if workspace.startup_failed():
        return EXIT_ERROR

    try:
        server = ExplorerServer(workspace, args.port, secrets.token_urlsafe(32), stop)
    except OSError as exc:
        print(
            f"error: cannot listen on 127.0.0.1:{args.port}: {exc.strerror or exc}",
            file=sys.stderr,
        )
        return EXIT_ERROR
    url = f"http://127.0.0.1:{server.port}/?token={server.token}"
    print(f"pyflowcharts explorer: {url}", flush=True)
    if not args.no_browser:
        open_browser(url)
    if not serve_forever:
        # No serve loop ever ran, so `shutdown()` would wait for one forever.
        stop.set()
        server.server_close()
        return EXIT_OK
    try:
        threading.Thread(
            target=watch,
            args=(workspace, server, stop),
            kwargs={"log": lambda line: print(line, file=sys.stderr)},
            daemon=True,
        ).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    finally:
        shutdown(server, stop)
    return EXIT_OK
