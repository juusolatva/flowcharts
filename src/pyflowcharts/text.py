"""Untrusted text (file names) in messages, labels and JSON.

On POSIX a file name can hold any bytes but ``/`` and NUL. Python keeps the bytes that are
not UTF-8 as lone surrogates (``surrogateescape``), which UTF-8 cannot encode, and a name
can also hold newlines and terminal control sequences.
"""

from __future__ import annotations

import re
import sys

_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def display(text: str) -> str:
    """``text`` with every character that is not printable escaped, for terminals and
    labels: an undecodable file-name byte as ``\\xff``, others as Python writes them
    (``\\n``, ``\\x1b``, ``\\u202e``). Printable text, ``café`` included, is unchanged."""
    if text.isprintable():
        return text
    return "".join(c if c.isprintable() else _escape(c) for c in text)


def _escape(char: str) -> str:
    code = ord(char)
    if 0xDC80 <= code <= 0xDCFF:  # surrogateescape: the original byte
        return f"\\x{code - 0xDC00:02x}"
    return char.encode("unicode_escape").decode("ascii")


def escape_surrogates(json_text: str) -> str:
    """JSON text from ``json.dumps(..., ensure_ascii=False)`` with lone surrogates written as
    ``\\udcff`` escapes, so it is valid UTF-8 and ``json.loads`` gives back the same string
    (and ``os.fsencode`` the same file name). Surrogates only occur inside JSON strings,
    where the escape means the same character."""
    return _LONE_SURROGATE.sub(lambda match: f"\\u{ord(match[0]):04x}", json_text)


def report(message: str) -> None:
    """Print a message line to stderr with :func:`display`, so a file name in it cannot
    break the line or send control sequences to the terminal."""
    print(display(message), file=sys.stderr)
