import json

import pytest

from pyflowcharts.text import display, escape_surrogates


@pytest.mark.parametrize(
    "text, shown",
    [
        ("café/mod.py", "café/mod.py"),  # printable text is kept
        ("a\nb.py", "a\\nb.py"),
        ("\x1b[2Jx.py", "\\x1b[2Jx.py"),  # a terminal escape sequence
        ("tab\there", "tab\\there"),
        ("bad-\udcff.py", "bad-\\xff.py"),  # an undecodable POSIX file-name byte
        ("lone-\ud800", "lone-\\ud800"),
        ("evil\u202eyp.txt", "evil\\u202eyp.txt"),  # right-to-left override
    ],
)
def test_display(text, shown):
    assert display(text) == shown


def test_escape_surrogates_keeps_json_reversible():
    text = escape_surrogates(json.dumps({"source": "bad-\udcff.py"}, ensure_ascii=False))
    assert text.encode("utf-8")  # valid UTF-8 now
    assert "\\udcff" in text
    assert json.loads(text) == {"source": "bad-\udcff.py"}
    assert escape_surrogates('{"x": "café"}') == '{"x": "café"}'
