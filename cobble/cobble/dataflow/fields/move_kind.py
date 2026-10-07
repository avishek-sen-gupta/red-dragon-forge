"""What a MOVE operand is, as far as whether the MOVE copies bytes one for one."""

from enum import Enum


class MoveKind(Enum):
    """A group, an alphanumeric item (or a reference-modified one), or anything else."""

    GROUP = "group"
    ALPHANUMERIC = "alphanumeric"
    OTHER = "other"
