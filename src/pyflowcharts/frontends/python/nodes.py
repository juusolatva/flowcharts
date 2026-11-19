"""Small queries on tree-sitter nodes shared by the statement converter and module charts:
statement children, docstrings, calls in assigned values, and type-alias statements."""

from __future__ import annotations

from tree_sitter import Node

EXTRAS = frozenset({"comment", "line_continuation"})


def named(node: Node) -> list[Node]:
    """Named children without the grammar's extras (comments, line continuations), which
    can appear anywhere, including before a statement's expression."""
    return [c for c in node.named_children if c.type not in EXTRAS]


def is_docstring(stmt: Node) -> bool:
    children = named(stmt)
    if stmt.type != "expression_statement" or len(children) != 1:
        return False
    value = children[0]
    # Module code reaches this after `ast` accepts it but before the tree-sitter error check,
    # so syntax newer than the grammar may parse with several children here; stop then, and
    # the module gets its "unsupported syntax" warning instead of a crash.
    while value.type == "parenthesized_expression" and len(inner := named(value)) == 1:
        value = inner[0]
    strings = value.named_children if value.type == "concatenated_string" else [value]
    return all(s.type == "string" and _is_plain_string(s) for s in strings)


def _is_plain_string(string: Node) -> bool:
    """Not an f-string or bytes (which ``ast`` does not treat as docstrings)."""
    start = string.children[0].text or b""
    return not any(c in b"fFbB" for c in start.rstrip(b"'\""))


def _contains_call(node: Node | None) -> bool:
    if node is None:
        return False
    if node.type == "call":
        return True
    return any(_contains_call(child) for child in node.children)


def calls_in_value(assignment: Node) -> bool:
    """Whether the assigned value contains a call. Chained assignments (``a = b = v``) nest
    on the right, and only the final value counts, as with ``ast``."""
    value = assignment.child_by_field_name("right")
    while value is not None and value.type == "assignment":
        value = value.child_by_field_name("right")
    return _contains_call(value)


def is_type_alias(node: Node) -> bool:
    """A real ``type X = ...`` statement has a name (or ``Name[T]``) on the left."""
    left = node.child_by_field_name("left")
    target = left.named_children[0] if left is not None and left.named_child_count else None
    return target is not None and target.type in ("identifier", "generic_type")
