"""Where a value written to a field came from, when it did not come from storage."""

from enum import StrEnum


class OriginKind(StrEnum):
    """The closed set of non-storage origins; NONE means the value came from storage."""

    NONE = "NONE"
    LITERAL = "LITERAL"
    FILE = "FILE"
    MAP = "MAP"
    CALL = "CALL"
    DYNAMIC_CALL = "DYNAMIC_CALL"
    CICS_STATE = "CICS_STATE"
    FUNCTION = "FUNCTION"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    FIGURATIVE = "FIGURATIVE"
    LENGTH_OF = "LENGTH_OF"
    UNRESOLVED_OPERAND = "UNRESOLVED_OPERAND"
    UNMODELLED = "UNMODELLED"
