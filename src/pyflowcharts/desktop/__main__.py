"""Run the desktop engine adapter: uv run python -m pyflowcharts.desktop."""

import io
import sys

from pyflowcharts.desktop.worker import serve


def main() -> None:
    # Pipes use the platform locale by default, which need not be UTF-8 on Windows.
    if isinstance(sys.stdin, io.TextIOWrapper):
        sys.stdin.reconfigure(encoding="utf-8")
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
