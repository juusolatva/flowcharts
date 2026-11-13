"""Shared helpers for the explorer server tests: a running server and a raw-socket client."""

import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from pyflowcharts.ir import ChartOptions

TOKEN = "test-token-value"
Headers = list[tuple[str, str]]


@dataclass
class RunningServer:
    port: int
    token: str
    cookie: str
    workspace: Any
    server: Any


@pytest.fixture
def running_server(tmp_path: Path) -> Iterator[RunningServer]:
    from pyflowcharts.explorer.server import ExplorerServer, shutdown
    from pyflowcharts.explorer.workspace import Workspace

    source = tmp_path / "a.py"
    source.write_text("def f():\n    pass\n")
    stop = threading.Event()
    workspace = Workspace([source], [], ChartOptions(), stop=stop)
    server = ExplorerServer(workspace, 0, TOKEN, stop)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield RunningServer(
            port=server.port,
            token=TOKEN,
            cookie=f"{server.cookie_name}={TOKEN}",
            workspace=workspace,
            server=server,
        )
    finally:
        shutdown(server, stop)
        thread.join(timeout=5)


def request(
    port: int,
    method: str,
    path: str,
    *,
    host: str | list[str] | None = "default",
    headers: dict[str, str] | None = None,
) -> tuple[int, Headers, bytes]:
    """Send one HTTP request over a raw socket and return ``(status, headers, body)``.

    ``host="default"`` sends ``127.0.0.1:PORT``, ``None`` sends no ``Host`` header and a list
    sends one ``Host`` header per item. Header names keep their case; look them up with ``header``.
    """
    hosts = (
        [f"127.0.0.1:{port}"] if host == "default" else [host] if isinstance(host, str) else host
    )
    lines = [f"{method} {path} HTTP/1.1"]
    lines += [f"Host: {value}" for value in hosts or []]
    lines += [f"{name}: {value}" for name, value in (headers or {}).items()]
    lines += ["Connection: close", "Content-Length: 0", "", ""]
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall("\r\n".join(lines).encode("latin-1"))
        chunks = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
    raw = b"".join(chunks)
    head, _, body = raw.partition(b"\r\n\r\n")
    status_line, *header_lines = head.decode("latin-1").split("\r\n")
    parsed = [tuple(line.split(": ", 1)) for line in header_lines]
    return int(status_line.split()[1]), [(n, v) for n, v in parsed], body


def header(headers: Headers, name: str) -> str | None:
    """First value of a response header, name compared case-insensitively."""
    return next((v for n, v in headers if n.lower() == name.lower()), None)
