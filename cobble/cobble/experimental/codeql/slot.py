"""Where a statement sits in its parent: a paragraph's body, a THEN or inline-PERFORM body, or an ELSE."""

from enum import IntEnum


class Slot(IntEnum):
    BODY = 0
    THEN = 1
    ELSE = 2
