"""The explorer's local HTTP server: Host, token and header checks, then routing."""

from __future__ import annotations

import contextlib
import hmac
import sys
import threading
import traceback
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pyflowcharts.explorer import api
from pyflowcharts.explorer.assets import load_asset
from pyflowcharts.explorer.workspace import Snapshot, Workspace

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
DISCONNECTS = (BrokenPipeError, ConnectionResetError)
STATIC_PREFIX = "/static/"
API_PREFIX = "/api/"
EVENTS_PATH = "/api/events"
PING_SECONDS = 15.0


class ExplorerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, workspace: Workspace, port: int, token: str, stop: threading.Event) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.workspace = workspace
        self.port: int = self.server_address[1]
        self.token = token
        self.cookie_name = f"pyflowcharts_token_{self.port}"
        self.stop = stop
        self.events = threading.Condition()

    def notify(self) -> None:
        """Wake every open event stream."""
        with self.events:
            self.events.notify_all()

    def handle_error(self, request: Any, client_address: Any) -> None:
        if not isinstance(sys.exc_info()[1], DISCONNECTS):
            super().handle_error(request, client_address)


def shutdown(server: ExplorerServer, stop: threading.Event) -> None:
    """Stop event streams first, then the serve loop, then close the socket."""
    stop.set()
    server.notify()
    server.shutdown()
    server.server_close()


def summary(snapshot: Snapshot) -> str:
    """One log line describing a re-parse."""
    files = len(snapshot.entries)
    warnings = len(snapshot.messages) + sum(len(e.skipped) for e in snapshot.entries)
    return (
        f"re-parsed {files} file{'' if files == 1 else 's'} (generation {snapshot.generation}), "
        f"{warnings} warning{'' if warnings == 1 else 's'}"
    )


def watch(
    workspace: Workspace,
    server: ExplorerServer,
    stop: threading.Event,
    *,
    interval: float = 1.0,
    log: Callable[[str], None] = print,
) -> None:
    """Poll for file changes until ``stop`` is set; log and wake the streams on each re-parse."""
    last_error: str | None = None
    while not stop.is_set():
        try:
            changed = workspace.refresh()
        except Exception as exc:  # noqa: BLE001 - a failed poll must not end the watcher
            message = f"error: refresh failed: {exc}"
            if message != last_error:
                log(message)
                if not isinstance(exc, OSError):  # unexpected: show where it came from
                    log(traceback.format_exc().rstrip())
            last_error = message
        else:
            last_error = None
            if changed:
                log(summary(workspace.current()))
                server.notify()
        stop.wait(interval)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server: ExplorerServer

    def log_message(self, format: str, *args: Any) -> None:
        """Stay silent: per-request logging would flood the terminal."""

    def handle(self) -> None:
        with contextlib.suppress(*DISCONNECTS):
            super().handle()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("do_"):
            return self._method_not_allowed
        raise AttributeError(name)

    # -- responses ---------------------------------------------------------------------------

    def respond(
        self,
        status: int,
        body: bytes = b"",
        content_type: str = "text/plain; charset=utf-8",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        if body:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def respond_text(self, status: HTTPStatus, headers: dict[str, str] | None = None) -> None:
        self.respond(status, status.phrase.encode() + b"\n", headers=headers)

    # -- checks ------------------------------------------------------------------------------

    def host_allowed(self) -> bool:
        hosts = self.headers.get_all("Host") or []
        port = self.server.port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        return len(hosts) == 1 and hosts[0].lower() in allowed

    def cookie_valid(self) -> bool:
        expected = self.server.token.encode()
        for header in self.headers.get_all("Cookie") or []:
            for part in header.split(";"):
                name, sep, value = part.strip().partition("=")
                matches = sep and name == self.server.cookie_name
                if matches and hmac.compare_digest(value.encode(), expected):
                    return True
        return False

    def token_valid(self, values: list[str]) -> bool:
        return len(values) == 1 and hmac.compare_digest(
            values[0].encode(), self.server.token.encode()
        )

    # -- dispatch ----------------------------------------------------------------------------

    def _method_not_allowed(self) -> None:
        if not self.host_allowed():
            return self.respond_text(HTTPStatus.FORBIDDEN)
        self.respond_text(HTTPStatus.METHOD_NOT_ALLOWED, {"Allow": "GET"})

    def do_GET(self) -> None:
        if not self.host_allowed():
            return self.respond_text(HTTPStatus.FORBIDDEN)
        url = urlsplit(self.path)
        query = parse_qs(url.query, keep_blank_values=True)
        if url.path == "/" and "token" in query:
            if not self.token_valid(query["token"]):
                return self.respond_text(HTTPStatus.FORBIDDEN)
            cookie = (
                f"{self.server.cookie_name}={self.server.token}; HttpOnly; SameSite=Lax; Path=/"
            )
            return self.respond(
                HTTPStatus.SEE_OTHER, headers={"Location": "/", "Set-Cookie": cookie}
            )
        if not self.cookie_valid():
            return self.respond_text(HTTPStatus.FORBIDDEN)
        self.route(url.path, query)

    def route(self, path: str, query: dict[str, list[str]]) -> None:
        """Dispatch an authenticated GET."""
        if path == "/":
            return self.serve_asset("index.html")
        if path.startswith(STATIC_PREFIX):
            return self.serve_asset(path[len(STATIC_PREFIX) :])
        if path == EVENTS_PATH:
            return self.serve_events()
        if path.startswith(API_PREFIX):
            return self.serve_api(path[len(API_PREFIX) :], query)
        self.respond_text(HTTPStatus.NOT_FOUND)

    def serve_events(self) -> None:
        """Stream a ``generation`` event per new snapshot, with a ping every 15 s of silence."""
        self.send_response(HTTPStatus.OK)
        for name, value in {**SECURITY_HEADERS, "Cache-Control": "no-store"}.items():
            self.send_header(name, value)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.flush()
        server = self.server
        last: int | None = None
        while True:
            with server.events:
                while not server.stop.is_set() and server.workspace.current().generation == last:
                    if not server.events.wait(PING_SECONDS):
                        break  # timed out: send a ping
                if server.stop.is_set():
                    return
                generation = server.workspace.current().generation
            if generation != last:
                self.wfile.write(f"event: generation\ndata: {generation}\n\n".encode())
                last = generation
            else:
                self.wfile.write(b": ping\n\n")
            self.wfile.flush()

    def serve_api(self, raw_path: str, query: dict[str, list[str]]) -> None:
        response = api.handle(raw_path, query, self.server.workspace.current())
        self.respond(
            response.status, response.body, response.content_type, {"Cache-Control": "no-store"}
        )

    def serve_asset(self, name: str) -> None:
        loaded = load_asset(name)
        if loaded is None:
            return self.respond_text(HTTPStatus.NOT_FOUND)
        body, content_type = loaded
        self.respond(HTTPStatus.OK, body, content_type, {"Cache-Control": "no-cache"})
