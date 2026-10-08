"""Which demand, other than a call site's, an explain row's source line accounts for."""

from enum import StrEnum


class ExplainSourceKind(StrEnum):
    """The program's own call-target reads; what its callers read back after it
    returns; and the part of that unresolved dynamic calls charge to every member."""

    CALL_TARGETS = "call-targets"
    READ_BACK = "read-back"
    READ_BACK_UNRESOLVED = "read-back-unresolved"
