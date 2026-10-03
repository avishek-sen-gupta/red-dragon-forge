"""How a CALL USING argument reaches the callee."""

from enum import StrEnum


class ArgumentMode(StrEnum):
    """REFERENCE shares the caller's storage; CONTENT and VALUE pass a copy."""

    REFERENCE = "REFERENCE"
    CONTENT = "CONTENT"
    VALUE = "VALUE"
