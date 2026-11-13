"""Render DOT source to SVG with the Graphviz ``dot`` executable."""

import subprocess


class RenderError(Exception):
    """Rendering failed; the message is suitable for showing to the user."""


def svg(dot_source: str, *, timeout: float = 30.0, dot: str = "dot") -> bytes:
    """Return the SVG for ``dot_source``, or raise `RenderError`."""
    try:
        result = subprocess.run(
            [dot, "-Tsvg"],
            input=dot_source.encode(),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise RenderError(f"rendering took longer than {timeout:g} s") from None
    except OSError as error:
        raise RenderError(f"Graphviz 'dot' could not be run: {error.strerror or error}") from error
    if result.returncode != 0:
        message = result.stderr.decode(errors="replace").strip()
        raise RenderError(message or f"dot exited with status {result.returncode}")
    return result.stdout
