"""What one line of a src-cfg file holds."""

from enum import StrEnum


class CfgRowType(StrEnum):
    PROGRAM = "program"
    NODE = "node"
    EDGE = "edge"
    CALL = "call"
    OUTCOME = "outcome"
    UNRESOLVED = "unresolved"
    REFUSED = "refused"
    SUMMARY = "summary"
