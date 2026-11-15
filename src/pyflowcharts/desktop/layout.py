"""Graphviz geometry for a native renderer; never stored in the semantic IR."""

from __future__ import annotations

import json
import subprocess
from typing import Any


class LayoutError(Exception):
    """A layout failure that can be displayed without ending the engine session."""


def graphviz_layout(dot_source: str, *, dot: str = "dot") -> dict[str, Any]:
    try:
        result = subprocess.run(
            [dot, "-Tjson"],
            input=dot_source.encode("utf-8"),
            capture_output=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise LayoutError("Graphviz layout exceeded 30 seconds") from None
    except OSError as error:
        raise LayoutError(
            f"Graphviz 'dot' could not be run: {error.strerror or error}. "
            "Install Graphviz and make sure dot is on PATH."
        ) from None
    if result.returncode:
        raise LayoutError(
            result.stderr.decode("utf-8", errors="replace").strip() or "Graphviz failed"
        )
    try:
        layout = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise LayoutError("Graphviz returned invalid JSON layout data") from None
    if not isinstance(layout, dict):
        raise LayoutError("Graphviz returned invalid JSON layout data")
    return layout
