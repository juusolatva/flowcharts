"""Run the desktop engine adapter: uv run python -m pyflowcharts.desktop."""

import io
import sys

from pyflowcharts.desktop.worker import serve


def main() -> None:
    # Frame bytes before decoding so malformed UTF-8 cannot consume later requests.
    input_stream = sys.stdin.buffer if isinstance(sys.stdin, io.TextIOWrapper) else sys.stdin
    # Pipes use the platform locale by default, which need not be UTF-8 on Windows.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    serve(input_stream, sys.stdout)


if __name__ == "__main__":
    main()
