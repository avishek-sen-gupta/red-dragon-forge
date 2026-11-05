"""A question's condition on one field at the point asked about."""

from dataclasses import dataclass
from enum import Enum


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
