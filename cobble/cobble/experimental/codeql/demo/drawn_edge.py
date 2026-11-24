"""An edge of the page: one of CodeQL's control-flow edges, or a step of a path one of the demo queries found."""

from enum import Enum


class DrawnEdge(Enum):
    FLOW = "FLOW"
    TRUE = "TRUE"
    FALSE = "FALSE"
    PERFORM = "PERFORM"
    RETURN = "RETURN"
    FALLTHRU = "FALLTHRU"
    GOTO = "GOTO"
    READ_TO_WRITE = "READ → WRITE"
    READ_TO_DISPLAY = "READ → DISPLAY"
