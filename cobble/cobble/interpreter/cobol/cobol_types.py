# pyright: standard
"""COBOL type descriptors — pure dataclasses for type metadata."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CobolDataCategory(str, Enum):
    """COBOL data type categories supported by the type system.

    The USAGE DISPLAY members correspond one-to-one to the single-byte data
    categories of the PICTURE clause (IBM Enterprise COBOL for z/OS 6.4 Language
    Reference, "Data categories and PICTURE rules", pp. 212-218). The multi-byte
    categories (DBCS, national, national-edited, UTF-8) are not modelled.
    """

    ZONED_DECIMAL = "ZONED_DECIMAL"
    COMP3 = "COMP3"
    BINARY = "BINARY"
    COMP1 = "COMP1"
    COMP2 = "COMP2"
    ALPHABETIC = "ALPHABETIC"
    ALPHANUMERIC = "ALPHANUMERIC"
    ALPHANUMERIC_EDITED = "ALPHANUMERIC_EDITED"
    NUMERIC_EDITED = "NUMERIC_EDITED"
    EXTERNAL_FLOAT = "EXTERNAL_FLOAT"


# The categories whose storage IS their character-position count: one byte per
# character position of the PICTURE character-string.
_DISPLAY_CATEGORIES = frozenset(
    {
        CobolDataCategory.ZONED_DECIMAL,
        CobolDataCategory.ALPHABETIC,
        CobolDataCategory.ALPHANUMERIC,
        CobolDataCategory.ALPHANUMERIC_EDITED,
        CobolDataCategory.NUMERIC_EDITED,
        CobolDataCategory.EXTERNAL_FLOAT,
    }
)


@dataclass(frozen=True)
class CobolTypeDescriptor:
    """Describes a COBOL data item's type and layout.

    Attributes:
        category: The data category (zoned, comp-3, alphanumeric).
        total_digits: Total digit positions for numeric types,
                      or character length for alphanumeric.
        decimal_digits: Implied decimal positions (0 for integers/alphanumeric).
        signed: Whether the numeric field is signed (S in PIC).
        char_positions: The picture's character-position count, i.e. its DISPLAY
                      size, computed per Table 12 (p. 208). This is what the
                      spec calls "the size of the elementary item", so it is
                      what USAGE DISPLAY storage costs. It differs from
                      total_digits whenever the picture holds symbols that are
                      digit positions but not character positions (P, V) or
                      character positions but not digit positions (insertion
                      characters, and the leading symbol of a floating run).
    """

    category: CobolDataCategory
    total_digits: int
    decimal_digits: int = 0
    signed: bool = False
    char_positions: int = 0
    sign_separate: bool = False
    sign_leading: bool = False
    justified_right: bool = False
    blank_when_zero: bool = False
    # The original PICTURE character-string, kept verbatim. NUMERIC_EDITED needs
    # it for the MOVE-time edit mask (sign/Z/comma/decimal positions); for the
    # other categories it is retained for diagnostics. Empty when there is no
    # PICTURE clause at all (COMP-1, COMP-2, USAGE POINTER).
    pic_string: str = ""

    @property
    def byte_length(self) -> int:
        """Compute the storage size in bytes for this type.

        - COMP3: packed BCD → (total_digits // 2) + 1 bytes.
        - BINARY: big-endian two's complement → 2/4/8 bytes by digit count.
        - COMP1: IEEE 754 single → 4 bytes (no PIC).
        - COMP2: IEEE 754 double → 8 bytes (no PIC).
        - every USAGE DISPLAY category: 1 byte per character position, which is
          exactly char_positions (already including the SIGN SEPARATE byte, and
          already excluding P and V, which the spec does not count in the size).
        """
        if self.category in _DISPLAY_CATEGORIES:
            return self.char_positions
        if self.category == CobolDataCategory.COMP3:
            return (self.total_digits // 2) + 1
        if self.category == CobolDataCategory.BINARY:
            if self.total_digits <= 4:
                return 2
            if self.total_digits <= 9:
                return 4
            return 8
        if self.category == CobolDataCategory.COMP1:
            return 4
        if self.category == CobolDataCategory.COMP2:
            return 8
        return self.total_digits  # fallback
