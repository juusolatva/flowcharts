"""Graphviz geometry for a native renderer; never stored in the semantic IR."""

from __future__ import annotations

import json
from typing import Any

from pyflowcharts.backends.dot_runner import DotFailed, DotNotFound, run_dot

LAYOUT_TIMEOUT = 30.0  # interactive: a layout that takes longer is reported, not awaited


class LayoutError(Exception):
    """A layout failure that can be displayed without ending the engine session."""


def graphviz_layout(dot_source: str, *, dot: str = "dot") -> dict[str, Any]:
    try:
        output = run_dot(dot_source, "json", timeout=LAYOUT_TIMEOUT, dot=dot)
    except DotNotFound:
        raise LayoutError(
            "Graphviz 'dot' could not be found. Install Graphviz and make sure dot is on PATH."
        ) from None
    except DotFailed as error:
        raise LayoutError(str(error)) from None
    try:
        layout = json.loads(output)
    except ValueError:  # includes UnicodeDecodeError
        raise LayoutError("Graphviz returned invalid JSON layout data") from None
    if not isinstance(layout, dict):
        raise LayoutError("Graphviz returned invalid JSON layout data")
    return layout
