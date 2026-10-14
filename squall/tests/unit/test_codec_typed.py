"""
tests/unit/test_codec_typed.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for COMP-3 (packed decimal) and BINARY codec helpers in squall.binding.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from squall.binding import (
    _comp3_decode,
    _comp3_encode,
    _binary_decode,
    _binary_encode,
)

from interpreter.cobol.cobol_constants import ByteConstants

# ── COMP-3 byte-size helper ──────────────────────────────────────────────────


def _comp3_size(total_digits: int) -> int:
    return (total_digits // 2) + 1


# ── _comp3_encode/_comp3_decode round-trip tests ─────────────────────────────


@pytest.mark.parametrize(
    "value, total_digits, decimal_digits, signed",
    [
        # ACCT-BAL case: PIC S9(7)V9(2) COMP-3  total=9, dec=2
        (Decimal("1234.56"), 9, 2, True),
        (Decimal("-0.01"), 9, 2, True),
        (Decimal("0.00"), 9, 2, True),
        (Decimal("9999999.99"), 9, 2, True),
        # Integer (no decimal scale)
        (Decimal("12345678"), 9, 0, True),
        # Large value total_digits=18
        (Decimal("123456789012345.67"), 18, 2, True),
        # Unsigned field
        (Decimal("42.50"), 9, 2, False),
        # Negative zero (should encode as zero)
        (Decimal("0.00"), 9, 2, True),
        # Explicit negative
        (Decimal("-9999999.99"), 9, 2, True),
    ],
)
def test_comp3_roundtrip(value, total_digits, decimal_digits, signed):
    encoded = _comp3_encode(value, total_digits, decimal_digits, signed)
    # Length must be (total_digits // 2) + 1
    assert len(encoded) == _comp3_size(
        total_digits
    ), f"Expected length {_comp3_size(total_digits)}, got {len(encoded)}"
    decoded = _comp3_decode(encoded, decimal_digits)
    assert (
        decoded == value
    ), f"Round-trip failed: {value!r} -> {encoded.hex()} -> {decoded!r}"


@pytest.mark.parametrize(
    "value, total_digits, decimal_digits, signed",
    [
        (Decimal("1234.56"), 9, 2, True),
        (Decimal("-0.01"), 9, 2, True),
        (Decimal("42.00"), 9, 2, False),
        (Decimal("-9999999.99"), 9, 2, True),
    ],
)
def test_comp3_sign_nibble(value, total_digits, decimal_digits, signed):
    """Last low nibble of encoded bytes must be correct sign nibble."""
    encoded = _comp3_encode(value, total_digits, decimal_digits, signed)
    last_byte = encoded[-1]
    sign_nibble = last_byte & ByteConstants.NIBBLE_MASK
    if value < 0:
        assert (
            sign_nibble == ByteConstants.SIGN_NIBBLE_NEGATIVE
        ), f"Expected negative sign nibble 0x0D for {value!r}, got 0x{sign_nibble:02X}"
    elif signed:
        assert (
            sign_nibble == ByteConstants.SIGN_NIBBLE_POSITIVE
        ), f"Expected positive sign nibble 0x0C for {value!r}, got 0x{sign_nibble:02X}"
    else:
        assert (
            sign_nibble == ByteConstants.SIGN_NIBBLE_UNSIGNED
        ), f"Expected unsigned sign nibble 0x0F for {value!r}, got 0x{sign_nibble:02X}"


def test_comp3_decode_known_bytes_acct_bal():
    """Decode a known ACCT-BAL byte pattern: 5 bytes for total_digits=9, dec=2.

    Pack 123456789 as 9 digits: 01 23 45 67 8C (positive signed → 0x0C low nibble).
    That represents integer 123456789 → with 2 decimal digits → Decimal('1234567.89').
    """
    # 9-digit, decimal_digits=2: encode Decimal("1234567.89")
    value = Decimal("1234567.89")
    encoded = _comp3_encode(value, 9, 2, signed=True)
    assert len(encoded) == 5
    decoded = _comp3_decode(encoded, decimal_digits=2)
    assert decoded == value


def test_comp3_decode_known_bytes_negative():
    """Manually craft negative packed BCD bytes and verify decode."""
    # -1.23 with total_digits=3, decimal_digits=2 → 1 byte: 0x12, sign nibble → 0x3D
    # Encoded: digits = "123", 2 bytes for (3//2)+1=2.
    # Byte 0: high=1, low=2 → 0x12
    # Byte 1: high=3, low=sign_negative(0xD) → 0x3D
    raw = bytes([0x12, 0x3D])
    result = _comp3_decode(raw, decimal_digits=2)
    assert result == Decimal("-1.23"), f"Expected Decimal('-1.23'), got {result!r}"


def test_comp3_decode_known_bytes_positive():
    """Manually craft positive packed BCD bytes and verify decode."""
    # +1.23 with sign_positive 0x0C
    # Byte 0: 0x12, Byte 1: 0x3C
    raw = bytes([0x12, 0x3C])
    result = _comp3_decode(raw, decimal_digits=2)
    assert result == Decimal("1.23"), f"Expected Decimal('1.23'), got {result!r}"


def test_comp3_decode_known_bytes_unsigned():
    """Packed BCD with unsigned sign nibble 0x0F."""
    # 1.23 unsigned
    # Byte 0: 0x12, Byte 1: 0x3F
    raw = bytes([0x12, 0x3F])
    result = _comp3_decode(raw, decimal_digits=2)
    assert result == Decimal("1.23"), f"Expected Decimal('1.23'), got {result!r}"


def test_comp3_encode_integer_scale():
    """COMP-3 with decimal_digits=0 (integer case, like 9(9) COMP-3)."""
    value = Decimal("123456789")
    encoded = _comp3_encode(value, 9, 0, signed=True)
    assert len(encoded) == 5
    decoded = _comp3_decode(encoded, decimal_digits=0)
    assert decoded == value


# ── _binary_decode/_binary_encode round-trip tests ───────────────────────────


@pytest.mark.parametrize(
    "value, total_digits, signed",
    [
        # 2-byte (total_digits <= 4)
        (0, 4, True),
        (1, 4, True),
        (-1, 4, True),
        (32767, 4, True),
        (-32768, 4, True),
        (65535, 4, False),
        # 4-byte (total_digits <= 9)
        (0, 9, True),
        (123456789, 9, True),
        (-123456789, 9, True),
        (2147483647, 9, True),
        (-2147483648, 9, True),
        # 8-byte (total_digits <= 18)
        (0, 18, True),
        (9223372036854775807, 18, True),
        (-9223372036854775808, 18, True),
    ],
)
def test_binary_roundtrip(value, total_digits, signed):
    # Compute expected byte length
    if total_digits <= 4:
        expected_len = 2
    elif total_digits <= 9:
        expected_len = 4
    else:
        expected_len = 8
    encoded = _binary_encode(value, expected_len, signed)
    assert len(encoded) == expected_len
    decoded = _binary_decode(encoded, signed)
    assert (
        decoded == value
    ), f"Round-trip failed: {value!r} -> {encoded.hex()} -> {decoded!r}"


def test_binary_decode_real_acct_id():
    """Decode ACCT-ID shape: PIC S9(9) COMP → 4 bytes big-endian, signed=True."""
    # ACCT-ID = 42 encoded as big-endian 4-byte signed int
    raw = (42).to_bytes(4, "big", signed=True)
    assert _binary_decode(raw, signed=True) == 42


def test_binary_decode_real_sqlcode_zero():
    """SQLCODE PIC S9(9) COMP: 0 → 4 bytes all zeros."""
    raw = (0).to_bytes(4, "big", signed=True)
    assert _binary_decode(raw, signed=True) == 0


def test_binary_decode_real_sqlcode_negative():
    """SQLCODE = -1 → 4-byte two's complement."""
    raw = (-1).to_bytes(4, "big", signed=True)
    assert _binary_decode(raw, signed=True) == -1


def test_binary_encode_big_endian_negative():
    """Negative BINARY value encodes as big-endian two's complement."""
    encoded = _binary_encode(-1, 4, signed=True)
    assert encoded == bytes([0xFF, 0xFF, 0xFF, 0xFF])
