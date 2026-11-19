"""Whether a ``match`` statement's last case always matches (then there is no "no match" exit)."""

from __future__ import annotations

from tree_sitter import Node


def irrefutable(case: Node) -> bool:
    """An irrefutable pattern (see ``_capture``) with no guard."""
    if case.child_by_field_name("guard") is not None:
        return False
    patterns = [c for c in case.named_children if c.type == "case_pattern"]
    if len(patterns) != 1 or any(c.type == "," for c in case.children):
        return False  # `case y,:` is a one-element sequence pattern
    return _capture(patterns[0])


def _capture(pattern: Node) -> bool:
    """Whether ``pattern`` (a ``case_pattern`` or an alternative of an or-pattern) always
    matches: ``_``, a capture name, one in parentheses, ``P as name`` with ``P`` irrefutable,
    or an or-pattern with an irrefutable alternative."""
    if pattern.type == "case_pattern":
        if pattern.child_count != 1:
            return False
        pattern = pattern.children[0]
    match pattern.type:
        case "_":
            return True
        case "dotted_name":
            return pattern.named_child_count == 1
        case "tuple_pattern":
            inner = [c for c in pattern.named_children if c.type == "case_pattern"]
            has_comma = any(c.type == "," for c in pattern.children)
            return len(inner) == 1 and not has_comma and _capture(inner[0])
        case "as_pattern":
            inner = next((c for c in pattern.named_children if c.type == "case_pattern"), None)
            return inner is not None and _capture(inner)
        case "union_pattern":
            return any(_capture(c) for c in pattern.children if c.type != "|")
    return False
