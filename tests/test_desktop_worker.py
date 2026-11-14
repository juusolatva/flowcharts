"""The native GUI talks to an engine through a versioned, browser-independent protocol."""

import io
import json
import os
import shutil
import subprocess
import sys

import pytest

from pyflowcharts.desktop.worker import Session, serve
from pyflowcharts.ir import SCHEMA_VERSION


def request(session, method, **params):
    return session.request({"protocol_version": 1, "id": 7, "method": method, "params": params})


def open_file(tmp_path, text="def f():\n    return 42\n\nf()\n", **kwargs):
    path = tmp_path / "café.py"
    path.write_text(text, encoding="utf-8")
    session = Session(**kwargs)
    result = request(session, "open", paths=[str(path)])
    assert result["ok"], result
    return session, path, result["result"]["snapshot"]


def test_open_reuses_ir_and_decoded_source(tmp_path):
    _, path, snapshot = open_file(tmp_path)
    assert snapshot["generation"] == 1
    assert snapshot["entries"][0]["source"] == str(path)
    document = snapshot["documents"][0]
    assert document["document"]["schema_version"] == SCHEMA_VERSION
    assert document["document"]["functions"][0]["qualname"] == "f"
    assert document["document"]["module"]["qualname"] == "<module>"
    assert document["source_text"] == path.read_text(encoding="utf-8")
    assert snapshot["edges"]


def test_source_uses_frontend_decoding_not_utf8_assumptions(tmp_path):
    path = tmp_path / "latin.py"
    path.write_bytes("# coding: latin-1\ndef f():\n    return 'é'\n".encode("latin-1"))
    result = request(Session(), "open", paths=[str(path)])
    assert "é" in result["result"]["snapshot"]["documents"][0]["source_text"]


def test_open_reports_errors_and_skipped_functions_without_crashing(tmp_path):
    _, _, snapshot = open_file(tmp_path, "def broken():\n    break\n")
    assert snapshot["entries"][0]["skipped"][0]["qualname"] == "broken"
    result = request(Session(), "open", paths=[str(tmp_path / "missing.py")])
    assert result["ok"]
    assert result["result"]["snapshot"]["entries"][0]["error"]


def test_empty_directory_can_be_opened(tmp_path):
    result = request(Session(), "open", paths=[str(tmp_path)])
    assert result["ok"]
    assert result["result"]["snapshot"]["documents"] == []


@pytest.mark.parametrize(
    "payload,code",
    [
        (None, "invalid_request"),
        ([], "invalid_request"),
        ({}, "invalid_request"),
        ({"protocol_version": True, "id": 1, "method": "open"}, "invalid_request"),
        ({"protocol_version": 99, "id": 1, "method": "open"}, "unsupported_protocol"),
        ({"protocol_version": 1, "id": True, "method": "open"}, "invalid_request"),
        ({"protocol_version": 1, "id": -1, "method": "open"}, "invalid_request"),
        ({"protocol_version": 1, "id": 1, "method": "open", "params": []}, "invalid_request"),
    ],
)
def test_invalid_envelopes(payload, code):
    response = Session().request(payload)
    assert response["protocol_version"] == 1
    assert response["ok"] is False
    assert response["error"]["code"] == code


@pytest.mark.parametrize("paths", [None, [], "a.py", [1], [""], [True]])
def test_open_validates_paths(paths):
    assert request(Session(), "open", paths=paths)["error"]["code"] == "invalid_request"


def test_unknown_method_and_requests_before_open():
    session = Session()
    assert request(session, "missing")["error"]["code"] == "unknown_method"
    assert request(session, "refresh")["error"]["code"] == "no_workspace"
    assert request(session, "graph", generation=1)["error"]["code"] == "no_workspace"


@pytest.mark.parametrize("method", ["open", "refresh", "graph"])
def test_unknown_parameters_are_not_silently_accepted(tmp_path, method):
    session, path, _ = open_file(tmp_path)
    params = {
        "open": {"paths": [str(path)]},
        "refresh": {},
        "graph": {"generation": 1, "document": None},
    }[method]
    response = request(session, method, **params, unsupported_option=True)
    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("line", ["x" * 500, "é" * 80])
def test_oversized_request_is_drained_and_next_request_is_read(monkeypatch, line):
    from pyflowcharts.desktop import worker

    monkeypatch.setattr(worker, "MAX_REQUEST_BYTES", 128)
    valid = '{"protocol_version":1,"id":2,"method":"refresh"}'
    output = io.StringIO()
    serve(io.StringIO(line + "\n" + valid), output)
    responses = [json.loads(frame) for frame in output.getvalue().splitlines()]
    assert responses[0]["error"]["code"] == "invalid_request"
    assert responses[1]["id"] == 2
    assert responses[1]["error"]["code"] == "no_workspace"


def test_refresh_only_publishes_changed_snapshots(tmp_path):
    session, path, _ = open_file(tmp_path)
    assert request(session, "refresh")["result"] == {"changed": False}
    path.write_text("def replacement():\n    pass\n", encoding="utf-8")
    result = request(session, "refresh")["result"]
    assert result["changed"]
    assert result["snapshot"]["generation"] == 2
    assert result["snapshot"]["entries"][0]["functions"][0]["qualname"] == "replacement"


def test_graph_is_separate_layout_data_and_cached_per_snapshot(tmp_path):
    calls = []

    def layout(dot):
        calls.append(dot)
        return {"objects": [{"name": "f#start"}], "edges": []}

    session, path, snapshot = open_file(tmp_path, layout=layout)
    params = {"generation": 1, "document": 0, "qualname": "f"}
    first = request(session, "graph", **params)
    assert first["ok"]
    assert first["result"]["layout"]["objects"][0]["name"] == "f#start"
    assert "layout" not in snapshot["documents"][0]["document"]
    assert request(session, "graph", **params) == first
    assert len(calls) == 1
    path.write_text("def f():\n    return 123\n", encoding="utf-8")
    request(session, "refresh")
    assert request(session, "graph", **params)["error"]["code"] == "stale_generation"
    assert request(session, "graph", **(params | {"generation": 2}))["ok"]
    assert len(calls) == 2


def test_module_and_callgraph_use_existing_dot_backends(tmp_path):
    calls = []

    def layout(dot):
        calls.append(dot)
        return {}

    session, _, _ = open_file(tmp_path, layout=layout)
    assert request(session, "graph", generation=1, document=0, qualname="<module>")["ok"]
    assert "<module>#start" in calls[-1]
    assert request(session, "graph", generation=1, document=None)["ok"]
    assert "cluster_0" in calls[-1]


@pytest.mark.parametrize(
    "params,code",
    [
        ({}, "invalid_request"),
        ({"generation": True, "document": None}, "invalid_request"),
        ({"generation": 0, "document": None}, "stale_generation"),
        ({"generation": 1}, "invalid_request"),
        ({"generation": 1, "document": -1, "qualname": "f"}, "not_found"),
        ({"generation": 1, "document": True, "qualname": "f"}, "invalid_request"),
        ({"generation": 1, "document": "0", "qualname": "f"}, "invalid_request"),
        ({"generation": 1, "document": 0}, "invalid_request"),
        ({"generation": 1, "document": 0, "qualname": "missing"}, "not_found"),
    ],
)
def test_graph_validates_generation_and_identity(tmp_path, params, code):
    session, _, _ = open_file(tmp_path)
    assert request(session, "graph", **params)["error"]["code"] == code


def test_layout_error_does_not_end_session_or_poison_cache(tmp_path):
    from pyflowcharts.desktop.layout import LayoutError

    calls = 0

    def layout(dot):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise LayoutError("dot failed")
        return {}

    session, _, _ = open_file(tmp_path, layout=layout)
    params = {"generation": 1, "document": 0, "qualname": "f"}
    assert request(session, "graph", **params)["error"]["message"] == "dot failed"
    assert request(session, "graph", **params)["ok"]


def test_stream_recovers_after_bad_json_and_preserves_unicode(tmp_path):
    path = tmp_path / "文件.py"
    path.write_text("def café():\n    pass\n", encoding="utf-8")
    payload = {"protocol_version": 1, "id": 42, "method": "open", "params": {"paths": [str(path)]}}
    output = io.StringIO()
    serve(io.StringIO("not json\n" + json.dumps(payload) + "\n"), output)
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert responses[0]["error"]["code"] == "invalid_request"
    assert responses[1]["id"] == 42
    assert responses[1]["ok"]
    assert "café" in output.getvalue()


def test_worker_entrypoint_uses_only_protocol_on_stdout():
    # Pytest's pythonpath setting is process-local; CI does not install the project.
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    result = subprocess.run(
        [sys.executable, "-m", "pyflowcharts.desktop"],
        env=env,
        input='{"protocol_version":1,"id":1,"method":"refresh"}\n',
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert len(result.stdout.splitlines()) == 1
    assert json.loads(result.stdout)["error"]["code"] == "no_workspace"
    assert result.stderr == ""


@pytest.mark.skipif(shutil.which("dot") is None, reason="Graphviz not installed")
def test_real_layout_includes_native_drawing_geometry(tmp_path):
    session, _, _ = open_file(tmp_path)
    response = request(session, "graph", generation=1, document=0, qualname="f")
    assert response["ok"], response
    layout = response["result"]["layout"]
    assert layout["bb"]
    assert {n["name"] for n in layout["objects"]} >= {"f#start", "f#end"}
    assert layout["objects"][0]["_draw_"]
    assert layout["edges"][0]["_draw_"]


@pytest.mark.parametrize("failure", ["missing", "timeout", "exit", "invalid_json"])
def test_layout_process_errors_are_actionable(monkeypatch, failure):
    from pyflowcharts.desktop.layout import LayoutError, graphviz_layout

    def run(*args, **kwargs):
        assert args[0] == ["custom-dot", "-Tjson"]
        assert kwargs["timeout"] == 30
        if failure == "missing":
            raise FileNotFoundError("not installed")
        if failure == "timeout":
            raise subprocess.TimeoutExpired("dot", 30)
        if failure == "exit":
            return subprocess.CompletedProcess([], 1, b"", b"bad graph")
        return subprocess.CompletedProcess([], 0, b"not json", b"")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(LayoutError):
        graphviz_layout("digraph {}", dot="custom-dot")
