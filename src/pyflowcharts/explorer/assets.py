"""The fixed table of static files the explorer serves."""

import functools
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import PurePosixPath

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
}


def _static() -> Traversable:
    return resources.files("pyflowcharts.explorer") / "static"


def _walk(directory: Traversable, prefix: str = "") -> list[str]:
    names: list[str] = []
    for entry in directory.iterdir():
        if entry.is_dir():
            names.extend(_walk(entry, f"{prefix}{entry.name}/"))
        elif PurePosixPath(entry.name).suffix in CONTENT_TYPES:
            names.append(f"{prefix}{entry.name}")
    return names


@functools.cache
def asset_names() -> frozenset[str]:
    """POSIX names, relative to ``static/``, of every servable file (fixed once installed)."""
    return frozenset(_walk(_static()))


def load_asset(name: str) -> tuple[bytes, str] | None:
    """Return ``(body, content type)`` for a known asset name, else ``None``."""
    if name not in asset_names():
        return None
    body = (_static() / name).read_bytes()
    return body, CONTENT_TYPES[PurePosixPath(name).suffix]
