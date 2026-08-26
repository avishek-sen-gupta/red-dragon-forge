"""PIC clause parser — full PICTURE grammar plus a semantic pass.

Parses COBOL PIC strings into :class:`CobolTypeDescriptor` instances. The
grammar lives in :mod:`interpreter.cobol.picture` (``picture.lark``) and covers
every single-byte USAGE DISPLAY data category of the PICTURE clause, so the
*category* is decided by which top-level alternative parses — nothing is
classified by symbol-set membership beforehand. Sizes, digit counts, scale and
the spec's non-context-free rules come from ``picture.analyse``.

Repeat counts ``(N)`` are a parser rule over a real integer terminal, so a count
is read STRUCTURALLY — there is no regex / string slicing anywhere. Counts are
also never expanded: ``X(32767)`` parses as one token with a count, not as 32767
symbols.

This module maps the spec's categories onto :class:`CobolDataCategory`, which
also carries the non-DISPLAY USAGE categories (COMP-3, binary, COMP-1/2). USAGE
wins for those: a ``numeric`` picture under ``USAGE COMP-3`` is packed decimal.

Numeric-edited pictures keep their original PIC string, because
:mod:`interpreter.cobol.edit_picture` needs it to build the MOVE-time edit mask.
Categorisation itself no longer goes through ``is_numeric_edited``.
"""

from __future__ import annotations

from lark.exceptions import UnexpectedInput

from cobble.interpreter.cobol import picture
from cobble.interpreter.cobol.cobol_types import CobolDataCategory, CobolTypeDescriptor

_USAGE_TO_CATEGORY = {
    "COMP-3": CobolDataCategory.COMP3,
    "COMP3": CobolDataCategory.COMP3,
    "PACKED-DECIMAL": CobolDataCategory.COMP3,
    "COMP": CobolDataCategory.BINARY,
    "COMP-4": CobolDataCategory.BINARY,
    "BINARY": CobolDataCategory.BINARY,
    "COMP-5": CobolDataCategory.BINARY,
    "COMP5": CobolDataCategory.BINARY,
    "COMP-1": CobolDataCategory.COMP1,
    "COMP1": CobolDataCategory.COMP1,
    "COMP-2": CobolDataCategory.COMP2,
    "COMP2": CobolDataCategory.COMP2,
}

# The grammar's top-level alternatives, in the spec's own naming, mapped onto the
# descriptor categories.
_PICTURE_CATEGORY = {
    "alphabetic": CobolDataCategory.ALPHABETIC,
    "alphanumeric": CobolDataCategory.ALPHANUMERIC,
    "alphanumeric_edited": CobolDataCategory.ALPHANUMERIC_EDITED,
    "numeric_edited": CobolDataCategory.NUMERIC_EDITED,
    "external_float": CobolDataCategory.EXTERNAL_FLOAT,
    # "numeric" is deliberately absent: its descriptor category comes from USAGE
    # (zoned decimal, packed decimal or binary), not from the picture.
}

# Categories for which total_digits historically carries the item's character
# width rather than a digit count. Nothing reads total_digits for these — the
# byte size comes from char_positions — but the two stay equal so the field keeps
# meaning "how long is this thing" for character data.
_WIDTH_AS_TOTAL_DIGITS = frozenset(
    {
        CobolDataCategory.ALPHABETIC,
        CobolDataCategory.ALPHANUMERIC,
        CobolDataCategory.ALPHANUMERIC_EDITED,
        CobolDataCategory.NUMERIC_EDITED,
    }
)

# Built once, at import. The default SPECIAL-NAMES: currency symbol "$" and a
# period for the decimal point. A compilation unit with a CURRENCY SIGN or
# DECIMAL-POINT IS COMMA clause needs its own parser from
# picture.build_parser(); wiring SPECIAL-NAMES through to here is not done yet.
_parser = picture.build_parser()


def parse_pic(
    pic: str,
    usage: str = "DISPLAY",
    sign_leading: bool = False,
    sign_separate: bool = False,
    justified_right: bool = False,
    blank_when_zero: bool = False,
) -> CobolTypeDescriptor:
    """Parse a COBOL PIC clause string into a CobolTypeDescriptor.

    Args:
        pic: The PIC string (e.g. "9(5)", "S9(5)V99", "X(8)", "$$$,$$9.99CR").
        usage: USAGE clause value ("DISPLAY", "COMP-3", "COMP").
        sign_leading: SIGN IS LEADING.
        sign_separate: SIGN IS SEPARATE CHARACTER — adds a character position.
        justified_right: JUSTIFIED RIGHT.
        blank_when_zero: BLANK WHEN ZERO — makes an otherwise numeric picture
            numeric-edited (p. 218), which the grammar alone cannot see.

    Returns:
        A CobolTypeDescriptor describing the field's type and layout.

    Raises:
        ValueError: if the string is not a legal PICTURE character-string.
    """
    usage_category = _USAGE_TO_CATEGORY.get(usage, CobolDataCategory.ZONED_DECIMAL)

    # COMP-1 and COMP-2 have no PIC clause — return immediately with fixed size.
    if usage_category in (CobolDataCategory.COMP1, CobolDataCategory.COMP2):
        return CobolTypeDescriptor(category=usage_category, total_digits=0)

    if not pic:
        return CobolTypeDescriptor(category=usage_category, total_digits=0)

    if pic.upper() == "POINTER":
        # A USAGE keyword that reaches this function as if it were a picture. No
        # stored digits; let the usage-derived category govern the result.
        return CobolTypeDescriptor(category=usage_category, total_digits=0)

    try:
        tree = _parser.parse(pic)
    except UnexpectedInput as exc:
        raise ValueError(f"Cannot parse PIC clause: {pic!r}") from exc

    analysis = picture.analyse(
        tree,
        sign_separate=sign_separate,
        blank_when_zero=blank_when_zero,
    )
    if analysis.errors:
        # The string has the shape of a picture but breaks a rule that depends on
        # a repeat count or on a run's length, so it would not compile (see
        # picture.analyse for the rules and their spec citations). No picture in
        # CardDemo or the production corpus reaches this: both corpora are 0 for it.
        raise ValueError(f"Invalid PIC clause: {pic!r}: " + "; ".join(analysis.errors))

    # USAGE governs the category for numeric pictures; the picture governs it for
    # every other category, because those are DISPLAY-only.
    category = _PICTURE_CATEGORY.get(analysis.category, usage_category)

    total_digits = (
        analysis.char_positions
        if category in _WIDTH_AS_TOTAL_DIGITS
        else analysis.digit_positions
    )

    return CobolTypeDescriptor(
        category=category,
        total_digits=total_digits,
        decimal_digits=analysis.scale,
        signed=analysis.signed,
        char_positions=analysis.char_positions,
        sign_separate=sign_separate,
        sign_leading=sign_leading,
        justified_right=justified_right,
        blank_when_zero=blank_when_zero,
        pic_string=pic,
    )
