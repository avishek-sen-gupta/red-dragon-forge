"""How a branch of a reachability walk ends."""

from enum import StrEnum


class ReachOutcome(StrEnum):
    RETURNS = "returns"
    STOP_RUN = "stop-run"
    GOBACK = "goback"
    EXIT_PROGRAM = "exit-program"
    ABEND = "abend"
    XCTL = "xctl"
    CICS_RETURN = "cics-return"
    UNHANDLED_CONDITION = "unhandled-condition"
    DEAD_END = "dead-end"
