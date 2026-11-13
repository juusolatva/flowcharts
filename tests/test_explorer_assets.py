from pathlib import Path

import pyflowcharts.explorer
from pyflowcharts.explorer.assets import CONTENT_TYPES, asset_names, load_asset


def test_assets_found_through_importlib_resources():
    assert "index.html" in asset_names()


def test_mjs_served_as_javascript():
    loaded = load_asset("views/app.mjs")
    assert loaded is not None
    body, content_type = loaded
    assert content_type == "text/javascript; charset=utf-8"
    assert isinstance(body, bytes)


def test_unknown_or_traversal_names_rejected():
    for name in ("../workspace.py", "x.py", "/etc/passwd", "../static/index.html"):
        assert load_asset(name) is None


def test_every_static_file_has_a_known_type():
    root = Path(pyflowcharts.explorer.__file__).parent / "static"
    files = [p for p in root.rglob("*") if p.is_file()]
    assert files
    assert {p.suffix for p in files} <= set(CONTENT_TYPES)
    assert asset_names() == {p.relative_to(root).as_posix() for p in files}
