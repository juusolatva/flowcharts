import shutil
import socket
import struct
import threading
import time

import pytest
from explorer_helpers import header, request

from pyflowcharts.explorer.server import (
    SECURITY_HEADERS,
    ExplorerServer,
    shutdown,
    summary,
    watch,
)
from pyflowcharts.explorer.workspace import Workspace
from pyflowcharts.ir import ChartOptions


def authed(rs):
    return {"Cookie": rs.cookie}


def test_missing_host_is_forbidden(running_server):
    status, _, _ = request(
        running_server.port, "GET", "/", host=None, headers=authed(running_server)
    )
    assert status == 403


def test_duplicate_host_is_forbidden(running_server):
    host = f"127.0.0.1:{running_server.port}"
    status, _, _ = request(
        running_server.port, "GET", "/", host=[host, host], headers=authed(running_server)
    )
    assert status == 403


def test_foreign_host_is_forbidden(running_server):
    status, _, _ = request(
        running_server.port,
        "GET",
        "/",
        host=f"evil.example:{running_server.port}",
        headers=authed(running_server),
    )
    assert status == 403


def test_wrong_port_in_host_is_forbidden(running_server):
    status, _, _ = request(
        running_server.port, "GET", "/", host="127.0.0.1:1", headers=authed(running_server)
    )
    assert status == 403


def test_localhost_any_case_accepted(running_server):
    status, _, body = request(
        running_server.port,
        "GET",
        "/",
        host=f"LOCALHOST:{running_server.port}",
        headers=authed(running_server),
    )
    assert status == 200
    assert b"<html" in body.lower()


def test_token_handshake_sets_port_scoped_lax_cookie(running_server):
    status, headers, _ = request(running_server.port, "GET", f"/?token={running_server.token}")
    assert status == 303
    assert header(headers, "Location") == "/"
    assert header(headers, "Set-Cookie") == (
        f"pyflowcharts_token_{running_server.port}={running_server.token}; "
        "HttpOnly; SameSite=Lax; Path=/"
    )


@pytest.mark.parametrize("query", ["?token=", "?token=x"])
def test_blank_or_wrong_query_token_rejected(running_server, query):
    status, headers, _ = request(
        running_server.port, "GET", f"/{query}", headers=authed(running_server)
    )
    assert status == 403
    assert header(headers, "Set-Cookie") is None


def test_cookie_found_after_malformed_sibling(running_server):
    cookie = f"bad[name]=1; {running_server.cookie}"
    status, _, _ = request(running_server.port, "GET", "/", headers={"Cookie": cookie})
    assert status == 200


def test_wrong_cookie_value_rejected(running_server):
    cookie = f"pyflowcharts_token_{running_server.port}=nope"
    status, _, _ = request(running_server.port, "GET", "/", headers={"Cookie": cookie})
    assert status == 403


def test_requests_without_cookie_rejected(running_server):
    status, _, _ = request(running_server.port, "GET", "/")
    assert status == 403
    status, _, _ = request(running_server.port, "GET", "/static/style.css")
    assert status == 403


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_other_methods_not_allowed(running_server, method):
    status, _, _ = request(running_server.port, method, "/", headers=authed(running_server))
    assert status == 405


def test_post_with_token_query_is_405_without_cookie(running_server):
    status, headers, _ = request(running_server.port, "POST", f"/?token={running_server.token}")
    assert status == 405
    assert header(headers, "Set-Cookie") is None


def test_post_with_foreign_host_is_forbidden(running_server):
    status, _, _ = request(
        running_server.port,
        "POST",
        "/",
        host=f"evil.example:{running_server.port}",
        headers=authed(running_server),
    )
    assert status == 403


def test_security_headers_on_every_response(running_server):
    port = running_server.port
    responses = [
        (200, request(port, "GET", "/", headers=authed(running_server))),
        (403, request(port, "GET", "/")),
        (404, request(port, "GET", "/nope", headers=authed(running_server))),
        (405, request(port, "POST", "/", headers=authed(running_server))),
    ]
    for expected, (status, headers, _) in responses:
        assert status == expected
        for name, value in SECURITY_HEADERS.items():
            assert header(headers, name) == value, (expected, name)


def test_static_responses_are_revalidated(running_server):
    status, headers, body = request(
        running_server.port, "GET", "/static/views/app.mjs", headers=authed(running_server)
    )
    assert status == 200
    assert header(
        headers,
        "Content-Type",
    ).startswith("text/javascript")
    assert header(headers, "Cache-Control") == "no-cache"
    assert header(headers, "Content-Length") == str(len(body))


def test_unknown_static_asset_404(running_server):
    for path in ("/static/nope.js", "/static/../workspace.py", "/static/"):
        status, _, _ = request(running_server.port, "GET", path, headers=authed(running_server))
        assert status == 404, path


def test_no_cors_headers(running_server):
    _, headers, _ = request(
        running_server.port,
        "GET",
        "/",
        headers={**authed(running_server), "Origin": "http://evil.example"},
    )
    assert not [n for n, _ in headers if n.lower().startswith("access-control-")]


def test_handler_uses_one_snapshot_per_request(running_server, monkeypatch):
    calls = []
    original = running_server.workspace.current

    def counting():
        calls.append(1)
        return original()

    monkeypatch.setattr(running_server.workspace, "current", counting)
    gen = original().generation
    status, headers, _ = request(
        running_server.port, "GET", f"/api/document/0?g={gen}", headers=authed(running_server)
    )
    assert status == 200
    assert header(headers, "Cache-Control") == "no-store"
    assert len(calls) == 1


def open_stream(rs, *, host=None, cookie=True):
    """Open ``/api/events`` on a raw socket; the caller closes it."""
    sock = socket.create_connection(("127.0.0.1", rs.port), timeout=5)
    lines = ["GET /api/events HTTP/1.1", f"Host: {host or f'127.0.0.1:{rs.port}'}"]
    if cookie:
        lines.append(f"Cookie: {rs.cookie}")
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
    return sock


def read_until(sock, marker: bytes) -> bytes:
    data = b""
    while marker not in data:
        chunk = sock.recv(4096)
        assert chunk, f"stream closed before {marker!r}: {data!r}"
        data += chunk
    return data


def test_event_stream_sends_initial_generation(running_server):
    with open_stream(running_server) as sock:
        data = read_until(sock, b"data: 1\n\n")
    head = data.partition(b"\r\n\r\n")[0].decode().lower()
    assert data.startswith(b"HTTP/1.0 200")
    assert "content-type: text/event-stream" in head
    assert "cache-control: no-store" in head
    assert "content-length" not in head
    assert "x-content-type-options: nosniff" in head
    assert b"event: generation\ndata: 1\n\n" in data


def test_event_stream_requires_cookie_and_host(running_server):
    port = running_server.port
    assert request(port, "GET", "/api/events")[0] == 403
    status, _, _ = request(
        port, "GET", "/api/events", host=f"evil.example:{port}", headers=authed(running_server)
    )
    assert status == 403


def test_event_stream_reports_new_generation(running_server, tmp_path):
    with open_stream(running_server) as sock:
        read_until(sock, b"data: 1\n\n")
        source = tmp_path / "a.py"
        source.write_text("def f():\n    return 1\n\n\ndef g():\n    pass\n")
        assert running_server.workspace.refresh()
        running_server.server.notify()
        read_until(sock, b"data: 2\n\n")


def test_client_disconnect_is_quiet(running_server, capsys, monkeypatch):
    monkeypatch.setattr("pyflowcharts.explorer.server.PING_SECONDS", 0.05)
    sock = open_stream(running_server)
    read_until(sock, b"data: 1\n\n")
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    sock.close()  # reset: the stream's next ping write fails
    time.sleep(0.5)  # several ping intervals
    assert request(running_server.port, "GET", "/", headers=authed(running_server))[0] == 200
    assert "Traceback" not in capsys.readouterr().err


def test_shutdown_with_several_open_streams_is_prompt(running_server):
    socks = [open_stream(running_server) for _ in range(5)]
    try:
        for sock in socks:
            read_until(sock, b"data: 1\n\n")
        started = time.monotonic()
        shutdown(running_server.server, running_server.server.stop)
        assert time.monotonic() - started < 2.0
        for sock in socks:  # every stream must end, not just shutdown() return
            sock.settimeout(2)
            while sock.recv(4096):
                pass
    finally:
        for sock in socks:
            sock.close()


def snapshot_of(tmp_path, files: dict[str, str]):
    paths = []
    for name, text in files.items():
        path = tmp_path / name
        path.write_text(text)
        paths.append(path)
    workspace = Workspace(paths, [], ChartOptions(), stop=threading.Event())
    return workspace.current()


def test_summary_counts_and_plurals(tmp_path):
    one = snapshot_of(tmp_path, {"a.py": "def f():\n    pass\n"})
    assert summary(one) == "re-parsed 1 file (generation 1), 0 warnings"
    broken = "def g():\n    x = = 1\n"
    two = snapshot_of(tmp_path, {"a.py": "def f():\n    pass\n", "b.py": broken})
    assert summary(two) == "re-parsed 2 files (generation 1), 1 warning"


class FakeServer:
    def __init__(self) -> None:
        self.notified = 0

    def notify(self) -> None:
        self.notified += 1


class OneLoopStop:
    """A stop event that reports not-set once, then set; ``wait`` records its timeouts."""

    def __init__(self, loops: int = 1) -> None:
        self.loops = loops
        self.waits: list[float] = []

    def is_set(self) -> bool:
        return self.loops <= 0

    def wait(self, timeout: float) -> bool:
        self.waits.append(timeout)
        self.loops -= 1
        return self.is_set()


def test_watch_logs_and_notifies(tmp_path):
    source = tmp_path / "a.py"
    source.write_text("def f():\n    pass\n")
    workspace = Workspace([source], [], ChartOptions(), stop=threading.Event())
    source.write_text("def f():\n    return 1\n\n\ndef g():\n    pass\n")
    server, stop, lines = FakeServer(), OneLoopStop(), []
    watch(workspace, server, stop, interval=0.25, log=lines.append)
    assert lines == ["re-parsed 1 file (generation 2), 0 warnings"]
    assert server.notified == 1
    assert stop.waits == [0.25]


def test_watch_does_not_notify_without_changes(tmp_path):
    source = tmp_path / "a.py"
    source.write_text("def f():\n    pass\n")
    workspace = Workspace([source], [], ChartOptions(), stop=threading.Event())
    server, lines = FakeServer(), []
    watch(workspace, server, OneLoopStop(), log=lines.append)
    assert lines == []
    assert server.notified == 0


def test_watch_survives_refresh_errors():
    class Flaky:
        def __init__(self) -> None:
            self.calls = 0

        def refresh(self) -> bool:
            self.calls += 1
            if self.calls == 1:
                raise PermissionError("denied")
            return False

    workspace, server, stop, lines = Flaky(), FakeServer(), OneLoopStop(2), []
    watch(workspace, server, stop, log=lines.append)
    assert workspace.calls == 2
    assert lines == ["error: refresh failed: denied"]
    assert len(stop.waits) == 2


@pytest.mark.skipif(shutil.which("dot") is None, reason="Graphviz not installed")
def test_non_ascii_qualname_reaches_api_percent_encoded(running_server, tmp_path):
    source = tmp_path / "u.py"
    source.write_text("def größe():\n    pass\n", encoding="utf-8")
    stop = threading.Event()
    workspace = Workspace([source], [], ChartOptions(), stop=stop)
    server = ExplorerServer(workspace, 0, "tok", stop)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, headers, body = request(
            server.port,
            "GET",
            "/api/svg/chart/0/gr%C3%B6%C3%9Fe?g=1",
            headers={"Cookie": f"{server.cookie_name}=tok"},
        )
    finally:
        shutdown(server, stop)
        thread.join(timeout=5)
    assert status == 200
    assert header(headers, "Content-Type") == "image/svg+xml"
    assert b"<svg" in body
