"""Decoded source text, the tree-sitter parse of it, label text and node locations."""

from __future__ import annotations

import unicodedata
from importlib.util import decode_source

import tree_sitter_python
from tree_sitter import Language, Node, Parser, Tree

from pyflowcharts.frontends.base import SourceError
from pyflowcharts.ir import SourceLocation

_PARSER = Parser(Language(tree_sitter_python.language()))

# A line break between tokens is dropped (not replaced by one space) next to these.
_NO_SPACE_AFTER = b"([{"
_NO_SPACE_BEFORE = b")]},."
_DROPPED = frozenset({"comment", "line_continuation"})


def identifier(node: Node) -> str:
    """A name or dotted name as Python reads it: NFKC-normalized (PEP 3131), so different
    spellings of one name (``é`` precomposed or as ``e`` plus an accent) are equal."""
    return unicodedata.normalize("NFKC", (node.text or b"").decode())


class Source:
    """A parsed file. ``data`` is the UTF-8 encoding of ``text``, so tree-sitter's byte
    columns are UTF-8 byte offsets (as with ``ast``) and rows match ``text``'s lines."""

    def __init__(self, text: str, path: str) -> None:
        self.path = path
        self.text = text
        self.data = text.encode()
        self.lines = self.data.split(b"\n")
        self.tree: Tree = _PARSER.parse(self.data)

    @classmethod
    def from_bytes(cls, raw: bytes, path: str) -> Source:
        if b"\x00" in raw:
            raise SourceError(path, "source code cannot contain null bytes")
        try:
            # decode_source honours coding cookies and BOMs and normalises newlines to "\n".
            text = decode_source(raw)
        except (SyntaxError, LookupError, UnicodeDecodeError) as e:
            raise SourceError(path, f"cannot decode source: {e}") from e
        return cls(text, path)

    # -- labels ---------------------------------------------------------------

    def source_text(self, node: Node) -> str:
        """The node's source with comments and continuations removed and line breaks
        between tokens joined by one space (none next to brackets, commas and dots).
        Same-line spacing and string literals are kept verbatim."""
        parts: list[bytes] = []
        previous: Node | None = None
        dropped = False  # a comment/continuation sat in the gap (so the gap is whitespace)
        for leaf in _leaves(node):
            if leaf.type in _DROPPED:
                dropped = True
                continue
            if previous is not None:
                gap = self.data[previous.end_byte : leaf.start_byte]
                if gap and (dropped or b"\n" in gap):
                    parts.append(self._joined_gap(previous, leaf))
                else:
                    parts.append(gap)  # same-line text is kept as written
            parts.append(self.data[leaf.start_byte : leaf.end_byte])
            previous, dropped = leaf, False
        return b"".join(parts).decode()

    def _joined_gap(self, previous: Node, leaf: Node) -> bytes:
        """What replaces a line break between two tokens: one space, or nothing next to a
        bracket, comma or dot (so a wrapped call reads ``g(1, 2)``)."""
        before = self.data[previous.end_byte - 1 : previous.end_byte]
        after = self.data[leaf.start_byte : leaf.start_byte + 1]
        if before in _NO_SPACE_AFTER or after in _NO_SPACE_BEFORE:
            return b""
        return b" "

    # -- locations ------------------------------------------------------------

    def location(self, node: Node) -> SourceLocation:
        end = _last_leaf(node)
        return SourceLocation(
            line=node.start_point.row + 1,
            column=node.start_point.column,
            end_line=end.end_point.row + 1,
            end_column=end.end_point.column,
        )


def _leaves(node: Node):
    """Tokens in source order, comments included; ``string`` nodes count as one token."""
    if node.child_count == 0 or node.type == "string":
        yield node
        return
    for child in node.children:
        yield from _leaves(child)


def _last_leaf(node: Node) -> Node:
    """The last descendant that is not a comment (tree-sitter blocks swallow trailing
    comments; ``ast`` ends at the last statement)."""
    for child in reversed(node.children):
        if child.type != "comment":
            return _last_leaf(child)
    return node
