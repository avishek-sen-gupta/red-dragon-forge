"""A question's condition on one field at the point asked about."""

from dataclasses import dataclass
from enum import Enum

from cobble.experimental.horn.context import Context
from cobble.experimental.horn.outcome import Outcome
from cobble.experimental.horn.point import Point


class Op(Enum):
    EQ = "=="
    NE = "!="


@dataclass(frozen=True)
class Part:
    """Bytes ``start`` to ``start + length - 1`` of a field, counted from 1 as a
    reference modification counts them."""

    field: str
    start: int
    length: int


@dataclass(frozen=True)
class Digits:
    """The digit halves of the bytes a ``Part`` with the same fields names: what a
    move into a number keeps of its sender, whatever zones and sign it writes."""

    field: str
    start: int
    length: int


@dataclass(frozen=True)
class Condition:
    field: str | Part | Digits
    op: Op
    value: str | Part | Digits


@dataclass(frozen=True)
class Visited:
    """Whether ``point`` has run: in this task, or in an earlier task that handed
    its commarea on to this one. Asked only of a point the lowering marks."""

    point: Point
    value: bool


@dataclass(frozen=True)
class Took:
    """Whether the TEST node ``test`` last took ``outcome``. Asked only of a test
    the lowering marks."""

    test: str
    outcome: Outcome


@dataclass(frozen=True)
class Entered:
    """Whether the last PERFORM into ``range`` was the node ``call``. Asked only of
    a range the lowering marks."""

    range: Context
    call: str
