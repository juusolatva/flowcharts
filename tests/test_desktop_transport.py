"""Byte-level recovery and source-path fidelity of the desktop worker transport."""

import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pyflowcharts.desktop.worker import serve


def test_deep_json_frame_does_not_stop_following_requests() -> None:
    deeply_nested = b"[" * 200_000 + b"]" * 200_000  # under 1 MiB
    valid = b'{"protocol_version":1,"id":7,"method":"refresh"}\n'
    output = io.StringIO()
    serve(io.BytesIO(deeply_nested + b"\n" + valid), output)
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(responses) == 2
    assert responses[0]["error"]["code"] == "invalid_request"
    assert responses[1]["id"] == 7
    assert responses[1]["error"]["code"] == "no_workspace"


@pytest.mark.skipif(os.name != "posix", reason="POSIX surrogateescaped file names")
@pytest.mark.skipif(shutil.which("dot") is None, reason="Graphviz not installed")
def test_non_utf8_file_name_survives_open_refresh_and_layout(tmp_path: Path) -> None:
    path = tmp_path / os.fsdecode(b"bad-\xff.py")
    path.write_text("def valid():\n    pass\n\nvalid()\n", encoding="utf-8")
    opening = {
        "protocol_version": 1,
        "id": 1,
        "method": "open",
        "params": {"paths": [str(tmp_path)]},
    }
    # The GUI asks for the call graph right after opening; the file name is in its labels.
    graphs = [
        {"protocol_version": 1, "id": 3, "method": "graph", "params": params}
        for params in (
            {"generation": 1, "document": None},
            {"generation": 1, "document": 0, "qualname": "<module>"},
        )
    ]
    requests = [opening, {"protocol_version": 1, "id": 2, "method": "refresh"}, *graphs]
    result = subprocess.run(
        [sys.executable, "-m", "pyflowcharts.desktop"],
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        input="".join(json.dumps(request) + "\n" for request in requests).encode(),
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8")
    responses = [json.loads(line) for line in result.stdout.decode("utf-8").splitlines()]
    assert len(responses) == 4
    snapshot = responses[0]["result"]["snapshot"]
    assert snapshot["entries"][0]["source"] == str(path)
    assert snapshot["documents"][0]["document"]["source"] == str(path)
    assert responses[1]["result"] == {"changed": False}
    for response in responses[2:]:
        assert response["ok"], response
        assert response["result"]["layout"]
    assert result.stderr == b""


@pytest.mark.parametrize("newline", [b"\n", b""])
def test_request_of_exactly_the_limit_is_accepted(monkeypatch, newline: bytes) -> None:
    from pyflowcharts.desktop import worker

    frame = b'{"protocol_version":1,"id":3,"method":"refresh"}'
    monkeypatch.setattr(worker, "MAX_REQUEST_BYTES", len(frame))
    output = io.StringIO()
    serve(io.BytesIO(frame + b"\n" + frame + b"x\n" + frame + newline), output)
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [r["error"]["code"] for r in responses] == [
        "no_workspace",
        "invalid_request",
        "no_workspace",
    ]
    assert [r["id"] for r in responses] == [3, None, 3]


def test_unexpected_engine_error_is_reported_and_session_continues(tmp_path: Path) -> None:
    from pyflowcharts.desktop.worker import Session

    (tmp_path / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
    calls = 0

    def layout(dot: str) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("directory vanished")
        return {}

    session = Session(layout=layout)
    opening = {"protocol_version": 1, "id": 1, "method": "open"}
    assert session.request(opening | {"params": {"paths": [str(tmp_path)]}})["ok"]
    graph = {
        "protocol_version": 1,
        "id": 2,
        "method": "graph",
        "params": {"generation": 1, "document": 0, "qualname": "f"},
    }
    failed = session.request(graph)
    assert failed["id"] == 2
    assert failed["error"]["code"] == "internal_error"
    assert "directory vanished" in failed["error"]["message"]
    assert session.request(graph)["ok"]


def test_unexpected_engine_error_logs_traceback_to_stderr(tmp_path: Path, capsys) -> None:
    from pyflowcharts.desktop.worker import Session

    (tmp_path / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")

    def layout(dot: str) -> dict:
        raise OSError("directory vanished")

    session = Session(layout=layout)
    opening = {"protocol_version": 1, "id": 1, "method": "open"}
    assert session.request(opening | {"params": {"paths": [str(tmp_path)]}})["ok"]
    graph = {"generation": 1, "document": 0, "qualname": "f"}
    session.request({"protocol_version": 1, "id": 2, "method": "graph", "params": graph})
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" in captured.err
    assert "layout" in captured.err
    assert "OSError: directory vanished" in captured.err
