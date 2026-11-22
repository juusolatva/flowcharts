"""Run the Graphviz ``dot`` executable on DOT source, with a time limit."""

from __future__ import annotations

import subprocess

# For the CLI's picture files. The call graph of a whole large project is legitimately slow
# (the Python standard library's takes about half a minute), so the limit only stops a
# `dot` that hangs. The desktop app's interactive layout uses a shorter one.
PICTURE_TIMEOUT = 300.0


class DotNotFound(Exception):
    """The ``dot`` executable is not installed or not on ``PATH``."""


class DotFailed(Exception):
    """``dot`` could not render the graph; the message can be shown to the user."""


def run_dot(dot_source: str, fmt: str, *, timeout: float, dot: str = "dot") -> bytes:
    """``dot -T<fmt>`` on ``dot_source``. Raises `DotNotFound` or `DotFailed`."""
    try:
        result = subprocess.run(
            [dot, f"-T{fmt}"],
            input=dot_source.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        raise DotNotFound from None
    except subprocess.TimeoutExpired:
        raise DotFailed(f"rendering took longer than {timeout:g} s") from None
    except OSError as error:
        raise DotFailed(f"Graphviz 'dot' could not be run: {error.strerror or error}") from None
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise DotFailed(message or f"dot exited with status {result.returncode}")
    return result.stdout
