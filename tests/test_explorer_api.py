import json
import re
import shutil

import pytest

from pyflowcharts.explorer import api
from pyflowcharts.explorer.render import RenderError
from pyflowcharts.explorer.workspace import Workspace, snapshot_json
from pyflowcharts.ir import ChartOptions
from pyflowcharts.serialize import from_json

needs_dot = pytest.mark.skipif(shutil.which("dot") is None, reason="Graphviz not installed")


def snap(tmp_path, text="def f():\n    pass\n\nf()\n", raw=None):
    path = tmp_path / "a.py"
    if raw is not None:
        path.write_bytes(raw)
    else:
        path.write_text(text, encoding="utf-8")
    return Workspace([path], [], ChartOptions()).current()


def get(snapshot, path, *, g=True, render=None):
    query = {"g": [str(snapshot.generation)]} if g is True else ({"g": [g]} if g else {})
    kwargs = {"render": render} if render else {}
    return api.handle(path, query, snapshot, **kwargs)


def fake_render(calls=None):
    def render(dot_source):
        if calls is not None:
            calls.append(dot_source)
        return b"<svg/>"

    return render


def test_state_matches_snapshot_json(tmp_path):
    s = snap(tmp_path)
    r = get(s, "state", g=False)
    assert r.status == 200
    assert r.content_type.startswith("application/json")
    assert json.loads(r.body) == snapshot_json(s)


def test_unknown_api_route_is_404_not_409(tmp_path):
    s = snap(tmp_path)
    for path in ("missing", "state/x", "document", "document/0/x", "svg/chart/0", "svg/other"):
        assert get(s, path, g=False).status == 404, path


def test_document_round_trips_through_from_json(tmp_path):
    s = snap(tmp_path)
    r = get(s, "document/0")
    assert r.status == 200
    assert from_json(r.body.decode()) == s.documents[0]


def test_stale_or_missing_generation_is_409(tmp_path):
    s = snap(tmp_path)
    for path in ("document/0", "source/0", "svg/callgraph", "svg/chart/0/f"):
        assert get(s, path, g="0").status == 409, path
        assert get(s, path, g=False).status == 409, path


def test_bad_indices_are_404(tmp_path):
    s = snap(tmp_path)
    for index in ("-1", "x", "99", "٢", ""):
        assert get(s, f"document/{index}").status == 404, index
        assert get(s, f"source/{index}").status == 404, index
        assert get(s, f"svg/chart/{index}/f").status == 404, index


def test_unknown_qualname_404(tmp_path):
    assert get(snap(tmp_path), "svg/chart/0/nope").status == 404


def test_invalid_percent_encoding_is_404(tmp_path):
    assert get(snap(tmp_path), "svg/chart/0/%FF").status == 404


def test_source_is_decoded_text(tmp_path):
    raw = "# -*- coding: latin-1 -*-\ndef f():\n    return 'é'\n".encode("latin-1")
    r = get(snap(tmp_path, raw=raw), "source/0")
    assert r.status == 200
    assert r.content_type == "text/plain; charset=utf-8"
    assert "é" in r.body.decode("utf-8")


def test_chart_svg_uses_render_and_cache(tmp_path):
    s = snap(tmp_path)
    calls = []
    first = get(s, "svg/chart/0/f", render=fake_render(calls))
    second = get(s, "svg/chart/0/f", render=fake_render(calls))
    assert (first.status, first.content_type, first.body) == (200, "image/svg+xml", b"<svg/>")
    assert second.body == b"<svg/>"
    assert len(calls) == 1


def test_callgraph_svg_is_cached(tmp_path):
    s = snap(tmp_path)
    calls = []
    for _ in range(2):
        r = get(s, "svg/callgraph", render=fake_render(calls))
        assert (r.status, r.body) == (200, b"<svg/>")
    assert len(calls) == 1


def test_render_happens_outside_the_cache_lock(tmp_path):
    s = snap(tmp_path)

    def render(dot_source):
        assert not s.svg_lock.locked()
        return b"<svg/>"

    assert get(s, "svg/chart/0/f", render=render).status == 200
    assert get(s, "svg/callgraph", render=render).status == 200


def test_module_chart_route(tmp_path):
    s = snap(tmp_path)
    assert get(s, "svg/chart/0/%3Cmodule%3E", render=fake_render()).status == 200


def test_module_route_404_without_module_chart(tmp_path):
    s = snap(tmp_path, text="def f():\n    pass\n")
    assert get(s, "svg/chart/0/%3Cmodule%3E", render=fake_render()).status == 404


def test_chart_svg_with_non_ascii_qualname(tmp_path):
    s = snap(tmp_path, text="def größe():\n    pass\n")
    r = get(s, "svg/chart/0/gr%C3%B6%C3%9Fe", render=fake_render())
    assert r.status == 200


def test_render_error_is_500_and_not_cached(tmp_path):
    s = snap(tmp_path)
    outcomes = [RenderError("boom"), b"<svg/>"]

    def render(dot_source):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    first = get(s, "svg/chart/0/f", render=render)
    assert (first.status, first.content_type, first.body) == (
        500,
        "text/plain; charset=utf-8",
        b"boom",
    )
    assert get(s, "svg/chart/0/f", render=render).status == 200


@needs_dot
def test_real_svg_contains_node_titles(tmp_path):
    s = snap(tmp_path)
    r = get(s, "svg/chart/0/f")
    assert r.status == 200
    svg = r.body.decode()
    groups = re.findall(r'<g id="[^"]*" class="node">\s*<title>([^<]*)</title>', svg)
    assert groups
    assert {n.id for n in s.documents[0].functions[0].nodes} <= set(groups)
