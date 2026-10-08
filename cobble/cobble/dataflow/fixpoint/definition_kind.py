"""What one write to a dynamic site's operand is, as far as resolving the site goes."""

from enum import StrEnum


class DefinitionKind(StrEnum):
    """Overwrites all of the operand with literals; copies it from other storage;
    or anything else -- weak, partial, unmodelled, arithmetic."""

    LITERAL = "literal"
    COPY = "copy"
    OTHER = "other"
