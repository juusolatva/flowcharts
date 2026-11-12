"""Language-neutral statement model that frontends produce and the builder consumes.

Every statement carries the source location its node is identified by. ``Block`` is a
tuple so that statements and blocks are hashable and immutable.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyflowcharts.ir import NodeKind, SourceLocation

type Block = tuple[Stmt, ...]


@dataclass(frozen=True)
class Step:
    """One process node; ``body`` (if any) continues from it, e.g. a ``with`` block.

    ``hidden`` steps (plain assignments) are shown only with ``show_variables`` or when
    their whole block would otherwise be empty (the reveal rule).
    """

    label: str
    loc: SourceLocation
    body: Block = ()
    hidden: bool = False


@dataclass(frozen=True)
class Arm:
    edge_label: str
    body: Block


@dataclass(frozen=True)
class Branch:
    """A decision node. ``default`` is an extra edge label that falls through to the next
    statement without a body (e.g. ``False`` for an ``if`` without ``else``)."""

    label: str
    loc: SourceLocation
    arms: tuple[Arm, ...]
    default: str | None


@dataclass(frozen=True)
class Loop:
    """``exit=None`` means only ``break`` leaves the loop."""

    label: str
    loc: SourceLocation
    enter: str
    exit: str | None
    body: Block
    orelse: Block


@dataclass(frozen=True)
class Handler:
    label: str
    loc: SourceLocation
    body: Block


@dataclass(frozen=True)
class Try:
    """``finalbody=None`` means no ``finally`` clause; ``()`` is a clause with no nodes."""

    loc: SourceLocation
    body: Block
    handlers: tuple[Handler, ...]
    orelse: Block
    finalbody: Block | None


@dataclass(frozen=True)
class Terminal:
    """``return`` or ``raise``: a node that leads straight to ``end``."""

    kind: NodeKind
    label: str
    loc: SourceLocation


@dataclass(frozen=True)
class Break:
    loc: SourceLocation


@dataclass(frozen=True)
class Continue:
    loc: SourceLocation


type Stmt = Step | Branch | Loop | Try | Terminal | Break | Continue
