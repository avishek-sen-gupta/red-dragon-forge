"""A question's condition on one field at the point asked about."""

from dataclasses import dataclass
from enum import Enum


class Op(Enum):
    EQ = "=="
    NE = "!="


@dataclass(frozen=True)
class Condition:
    field: str
    op: Op
    value: str
