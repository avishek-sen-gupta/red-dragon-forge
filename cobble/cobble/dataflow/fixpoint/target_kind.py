"""What a dynamic site's operand names: the program a call transfers to, or the CICS file a statement touches."""

from __future__ import annotations

from enum import StrEnum

CICS_FILE_NAME_LIMIT = 8


class TargetKind(StrEnum):
    """The kind of thing a dynamic site's resolved values must be able to name."""

    PROGRAM = "program"
    FILE = "file"

    def can_name(self, value: str) -> bool:
        """A resolved value that could name this kind of thing.

        Not a pattern standing in for a type: every value here is already known to be
        the content of an operand of this kind, and this only rejects content that
        cannot name anything at all -- or, for a CICS file, a name longer than CICS
        allows.
        """
        readable = bool(value) and value.isprintable() and not value.isspace()
        if self is TargetKind.FILE:
            return readable and len(value) <= CICS_FILE_NAME_LIMIT
        return readable
