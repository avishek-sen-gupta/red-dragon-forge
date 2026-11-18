"""What one field's type hint becomes in the dbscheme: a column, a node, a location, or a table of them."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ScalarKind(Enum):
    STRING = "string"
    INT = "int"
    BOOLEAN = "boolean"


@dataclass(frozen=True)
class Scalar:
    """An enum is a string column holding its value."""

    kind: ScalarKind


@dataclass(frozen=True)
class NodeRef:
    """A node of the dbscheme type ``@<name>``: a dataclass, or a union of them."""

    name: str


@dataclass(frozen=True)
class Located:
    """A ``SourceSpan``: the node's place in its file."""


@dataclass(frozen=True)
class Absent:
    """``X | None``: a row only when the field holds an ``X``."""

    inner: Shape


@dataclass(frozen=True)
class Repeated:
    """A list or a variadic tuple: one row per element, with its index."""

    element: Shape


@dataclass(frozen=True)
class Keyed:
    """``dict[str, X]``: one row per entry, with its index and key."""

    value: Shape


Shape = Scalar | NodeRef | Located | Absent | Repeated | Keyed
