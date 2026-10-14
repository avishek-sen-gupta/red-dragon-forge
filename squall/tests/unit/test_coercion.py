"""
tests/unit/test_coercion.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Strict coercion layer: a SQL value whose type doesn't match its host var's COBOL
type fails immediately with a genuine-failure SQLCODE. The tolerant convert/warn
path (production DB2 assignment rules) is deferred — tracked as squall-ud0.
"""

from __future__ import annotations

from decimal import Decimal

from interpreter.cobol.field_position import FieldPosition

from squall.binding import (
    _assignability,
    SQLCODE_INCOMPATIBLE_TYPE,
    SQLCODE_VALUE_OUT_OF_RANGE,
    SQLCODE_NULL_NO_INDICATOR,
)


def _numeric(
    category: str, total_digits: int, decimal_digits: int = 0
) -> FieldPosition:
    return FieldPosition(
        offset=0,
        length=(total_digits // 2) + 1,
        category=category,
        total_digits=total_digits,
        decimal_digits=decimal_digits,
        signed=True,
    )


def _alpha(length: int) -> FieldPosition:
    return FieldPosition(
        offset=0,
        length=length,
        category="ALPHANUMERIC",
        total_digits=length,
        decimal_digits=0,
        signed=False,
    )


# ── Compatible assignments → 0 ────────────────────────────────────────────────


def test_int_into_numeric_ok() -> None:
    assert _assignability(500, _numeric("ZONED_DECIMAL", 9)) == 0


def test_decimal_matching_scale_ok() -> None:
    assert _assignability(Decimal("1234.56"), _numeric("COMP3", 9, 2)) == 0


def test_float_matching_scale_ok() -> None:
    assert _assignability(1234.56, _numeric("COMP3", 9, 2)) == 0


def test_fewer_fraction_digits_ok() -> None:
    # scale 2 field, value with scale 0 — no loss.
    assert _assignability(5, _numeric("COMP3", 9, 2)) == 0


def test_str_fits_alpha_ok() -> None:
    assert _assignability("ALICE", _alpha(20)) == 0


def test_str_exact_length_ok() -> None:
    assert _assignability("ABCDE", _alpha(5)) == 0


# ── Cross-family → -301 ───────────────────────────────────────────────────────


def test_str_into_numeric_incompatible() -> None:
    assert _assignability("HELLO", _numeric("BINARY", 9)) == SQLCODE_INCOMPATIBLE_TYPE


def test_number_into_alpha_incompatible() -> None:
    assert _assignability(500, _alpha(10)) == SQLCODE_INCOMPATIBLE_TYPE


def test_bool_into_numeric_incompatible() -> None:
    # bool is an int subclass but never a valid numeric SQL value here.
    assert _assignability(True, _numeric("BINARY", 9)) == SQLCODE_INCOMPATIBLE_TYPE


# ── Overflow / precision loss → -304 ──────────────────────────────────────────


def test_integer_overflow() -> None:
    assert (
        _assignability(123456789, _numeric("ZONED_DECIMAL", 4))
        == SQLCODE_VALUE_OUT_OF_RANGE
    )


def test_excess_scale_lost() -> None:
    assert (
        _assignability(Decimal("1.234"), _numeric("COMP3", 9, 2))
        == SQLCODE_VALUE_OUT_OF_RANGE
    )


def test_decimal_into_integer_field_lossy() -> None:
    # A fractional value into a scale-0 (integer) field would lose the fraction.
    assert (
        _assignability(Decimal("12.5"), _numeric("BINARY", 9, 0))
        == SQLCODE_VALUE_OUT_OF_RANGE
    )


def test_str_too_long_truncation() -> None:
    assert _assignability("TOOLONG", _alpha(4)) == SQLCODE_VALUE_OUT_OF_RANGE


# ── NULL without indicator → -305 ─────────────────────────────────────────────


def test_null_into_numeric() -> None:
    assert (
        _assignability(None, _numeric("ZONED_DECIMAL", 9)) == SQLCODE_NULL_NO_INDICATOR
    )


def test_null_into_alpha() -> None:
    assert _assignability(None, _alpha(10)) == SQLCODE_NULL_NO_INDICATOR
