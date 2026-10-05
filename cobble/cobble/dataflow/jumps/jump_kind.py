"""JumpKind — the statements that move control or data between programs."""

from enum import Enum


class JumpKind(Enum):
    XCTL = "XCTL"
    LINK = "LINK"
    CALL = "CALL"
    RETURN_TRANSID = "RETURN_TRANSID"
    START = "START"
    EXIT = "EXIT"
    RETRIEVE = "RETRIEVE"
    ENTRY = "ENTRY"
