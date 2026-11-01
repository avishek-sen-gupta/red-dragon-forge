"""Whether a read's bytes are carried by the statement or only decide what it does."""

from __future__ import annotations

from enum import Enum


class ReadKind(Enum):
    """COPIED: the bytes are what the statement moves, into a target or out to a file,
    screen or callee. CONSULTED: the value decides which data is taken or which way
    control goes -- a subscript, a key, a RIDFLD, a test's operand -- and none of its
    bytes are moved."""

    COPIED = "copied"
    CONSULTED = "consulted"
