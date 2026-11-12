"""Decoded source text, the tree-sitter parse of it, label text and node locations."""

from __future__ import annotations

from importlib.util import decode_source

import tree_sitter_python
from tree_sitter import Language, Node, Parser, Tree

from pyflowcharts.frontends.base import SourceError
from pyflowcharts.ir import SourceLocation

_PARSER = Parser(Language(tree_sitter_python.language()))

# Whitespace between tokens is dropped (not replaced by one space) next to these.
_NO_SPACE_AFTER = b"([{"
_NO_SPACE_BEFORE = b")]},."
_DROPPED = frozenset({"comment", "line_continuation"})


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
        """The node's source with comments and continuations removed and whitespace gaps
        between tokens collapsed to one space (none next to brackets, commas and dots).
        String literals are kept verbatim."""
        parts: list[bytes] = []
        previous: Node | None = None
        dropped = False  # a comment/continuation sat in the gap (so the gap is whitespace)
        for leaf in _leaves(node):
            if leaf.type in _DROPPED:
                dropped = True
                continue
            if previous is not None:
                gap = self.data[previous.end_byte : leaf.start_byte]
                if gap and (dropped or gap.isspace()):
                    before = self.data[previous.end_byte - 1 : previous.end_byte]
                    after = self.data[leaf.start_byte : leaf.start_byte + 1]
                    if before not in _NO_SPACE_AFTER and after not in _NO_SPACE_BEFORE:
                        parts.append(b" ")
                else:
                    parts.append(gap)
            parts.append(self.data[leaf.start_byte : leaf.end_byte])
            previous, dropped = leaf, False
        return b"".join(parts).decode()

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
