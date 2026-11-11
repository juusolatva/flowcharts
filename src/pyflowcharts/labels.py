"""Label text helpers shared by all frontends."""

ELLIPSIS = "…"


def shorten(text: str, max_length: int) -> str:
    """Collapse whitespace runs to single spaces and truncate to ``max_length`` with an ellipsis."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_length:
        return collapsed
    return collapsed[: max_length - 1] + ELLIPSIS
