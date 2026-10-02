"""A numeric literal's digits as they land in a field: duplicates RedDragon's interpreter/cobol/data_filters.py left_adjust and align_decimal, because cobble may not import the interpreter (red-dragon-forge-bcg)."""

from __future__ import annotations


def aligned_digits(value: str, total_digits: int, decimal_digits: int) -> str:
    """Sign and point dropped; the integer part right-justified and zero-filled to
    its positions, keeping its rightmost digits; the fraction zero-filled after it,
    keeping its leftmost."""
    whole, _, fraction = value.strip().lstrip("+-").partition(".")
    return (
        _right_justified(whole, total_digits - decimal_digits)
        + fraction.ljust(decimal_digits, "0")[:decimal_digits]
    )


def _right_justified(digits: str, width: int) -> str:
    if width <= 0:
        return ""
    return digits.zfill(width)[-width:]
