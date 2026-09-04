"""Literal and figurative constant recognition.

Shared vocabulary for filtering literals from dependency lists. A literal that appears
in a node's reads or a guard operand is not a field dependency.
"""

from __future__ import annotations

# F8/F9: Add missing singular/plural variants and handle positive signed numerics
FIGURATIVE_CONSTANTS = frozenset(
    {
        "SPACES",
        "SPACE",
        "LOW-VALUES",
        "LOW-VALUE",
        "HIGH-VALUES",
        "HIGH-VALUE",
        "ZERO",
        "ZEROS",
        "ZEROES",
        "NULL",
        "NULLS",
        "QUOTE",
        "QUOTES",
    }
)


def is_literal(name: str) -> bool:
    """Check if a name is a quoted literal, numeric literal, or figurative constant.

    Literals land in Node.reads (e.g., MOVE 'F' TO X reports reads=("'F'",)) and in
    guard atom operands. Without filtering, every pair of MOVE SPACES TO X / MOVE
    SPACES TO Y in one paragraph reports as SAME_SOURCE on the strength of a shared
    literal, and every field written under IF WS-A = 'Y' reports 'Y' as a dependency.

    Covers:
    - Empty string: treated as a literal (not a field name)
    - Quoted literals: 'ABC', "XYZ"
    - Numeric literals: 123, -456, +789, 12.34
    - Figurative constants: SPACES, LOW-VALUES, ZERO, etc.
    - Prefixed forms: ALL '-', X'40', N'...', Z'...', G'...', B'...'

    Returns True for literals (should be filtered), False for field names.

    After widening, verify whole-token matching: ALL-ITEMS, ALLOCATION, X-FLAG,
    ZERO-BALANCE, LOW-LIMIT, QUOTE-COUNT must all return False.
    """
    # F-new-3: Empty string is not a field name
    if not name:
        return True
    # Quoted strings
    if (name.startswith("'") and name.endswith("'")) or (
        name.startswith('"') and name.endswith('"')
    ):
        return True
    # Numeric literals (F8: include positive sign)
    if name.replace("+", "").replace("-", "").replace(".", "").isdigit():
        return True
    # Figurative constants (whole-token match)
    if name in FIGURATIVE_CONSTANTS:
        return True
    # ALL with literal: "ALL '-'" (space after ALL is load-bearing)
    if name.startswith("ALL "):
        return True
    # Prefixed literals: X'40', N'...', Z'...', G'...', B'...'
    return len(name) >= 3 and name[0] in "XNZGB" and name[1] == "'" and name[-1] == "'"
