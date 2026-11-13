import pytest
from explorer_helpers import header, request

from pyflowcharts.explorer.server import SECURITY_HEADERS


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
