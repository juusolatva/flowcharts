"""Label text taken from the original source, so literals keep the form the author wrote."""

from __future__ import annotations

import ast
from importlib.util import decode_source


class SourceText:
    def __init__(self, source: bytes) -> None:
        # decode_source honours coding cookies and BOMs and translates newlines to "\n",
        # matching how ast numbers lines. AST columns are UTF-8 byte offsets, hence encode().
        self._lines = [line.encode() for line in decode_source(source).split("\n")]

    def text(self, node: ast.AST) -> str:
        """The node's source text if it sits on one line, else ``ast.unparse``.

        Multi-line segments could carry comments and ``\\`` continuations into the label.
        """
        line = getattr(node, "lineno", None)
        col = getattr(node, "col_offset", None)
        end_line = getattr(node, "end_lineno", None)
        end_col = getattr(node, "end_col_offset", None)
        if line is not None and line == end_line and col is not None and end_col is not None:
            return self._lines[line - 1][col:end_col].decode()
        return ast.unparse(node)
