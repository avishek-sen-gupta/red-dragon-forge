"""
squall.binding
~~~~~~~~~~~~~~
Dialect-agnostic bridge between COBOL host-variable fields and SQL params/results.

All functions are pure (no global mutable state). The VM interface is duck-typed:
any object with ``call_stack``, ``data_layout``, and ``region_get`` satisfies it.

Supported codec categories (slice 1 + 2):
  - ZONED_DECIMAL  (PIC 9 / S9 DISPLAY)  → int
  - ALPHANUMERIC   (PIC X)               → str
  - COMP3          (PIC S9 COMP-3)       → Decimal
  - BINARY         (PIC S9 COMP/COMP-4)  → int
"""

from __future__ import annotations

import sys
import os
from decimal import Decimal

# Resolve vendor path so ByteConstants can be imported without installing red-dragon
# as an editable package in every environment.
_VENDOR = os.path.join(os.path.dirname(__file__), "..", "vendor", "red-dragon")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

from interpreter.cobol.cobol_constants import ByteConstants  # noqa: E402
from interpreter.var_name import VarName  # noqa: E402
from interpreter.address import Address  # noqa: E402

# ── Low-level codec helpers ───────────────────────────────────────────────────


def _zoned_decode(data: bytes) -> int:
    """Decode ZONED_DECIMAL bytes to a signed integer.

    Each byte encodes one decimal digit in its low nibble.
    The *last* byte's high nibble is the sign zone:
      0xD -> negative; anything else -> positive / unsigned.
    """
    if not data:
        return 0
    digits = [b & ByteConstants.NIBBLE_MASK for b in data]
    sign_zone = (data[-1] & ByteConstants.HIGH_NIBBLE_MASK) >> 4
    value = int("".join(str(d) for d in digits))
    if sign_zone == (ByteConstants.SIGN_NIBBLE_NEGATIVE & ByteConstants.NIBBLE_MASK):
        value = -value
    return value


def _zoned_encode(n: int, length: int) -> bytes:
    """Encode a signed integer as ZONED_DECIMAL bytes of the given length.

    Digits are right-justified and zero-filled. Every byte uses the unsigned
    zone nibble (0xF) except the last byte, which carries the sign zone:
      negative -> 0xD; non-negative -> 0xF (unsigned/positive).
    """
    abs_digits = list(str(abs(n)).zfill(length)[-length:])  # right-justify, truncate
    result = bytearray(length)
    unsigned_zone = (ByteConstants.SIGN_NIBBLE_UNSIGNED & ByteConstants.NIBBLE_MASK) << 4  # 0xF0
    for i, ch in enumerate(abs_digits):
        digit = int(ch)
        if i < length - 1:
            result[i] = unsigned_zone | digit
        else:
            # Last byte: sign zone
            if n < 0:
                sign_zone = (ByteConstants.SIGN_NIBBLE_NEGATIVE & ByteConstants.NIBBLE_MASK) << 4  # 0xD0
            else:
                sign_zone = unsigned_zone  # 0xF0
            result[i] = sign_zone | digit
    return bytes(result)


def _alpha_decode(data: bytes) -> str:
    """Decode ALPHANUMERIC EBCDIC bytes to a Python str, stripping trailing spaces."""
    return data.decode("cp037").rstrip()


def _alpha_encode(s: str, length: int) -> bytes:
    """Encode a Python str to ALPHANUMERIC EBCDIC bytes, space-padded / truncated."""
    ebcdic_space = bytes([ByteConstants.EBCDIC_SPACE])
    encoded = s.encode("cp037")
    if len(encoded) >= length:
        return encoded[:length]
    return encoded + ebcdic_space * (length - len(encoded))


# ── COMP-3 (packed decimal) codec ────────────────────────────────────────────


def _comp3_decode(data: bytes, decimal_digits: int) -> Decimal:
    """Decode COMP-3 packed BCD bytes to a Decimal.

    Packed BCD layout:
      - Each byte holds two decimal digits (high nibble, low nibble).
      - The final byte's LOW nibble is the sign:
          0x0D → negative; 0x0C → positive (signed); 0x0F → unsigned (treat as positive).
      - All other nibbles are digit values.

    Args:
        data: Packed BCD bytes of length (total_digits // 2) + 1.
        decimal_digits: Number of implied decimal positions.

    Returns:
        Decoded value as Decimal.
    """
    if not data:
        return Decimal("0")

    # Extract sign nibble from last byte's low nibble
    last_byte = data[-1]
    sign_nibble = last_byte & ByteConstants.NIBBLE_MASK
    negative = sign_nibble == ByteConstants.SIGN_NIBBLE_NEGATIVE

    # Extract all digit nibbles: high nibbles of all bytes + high nibble of last byte;
    # the low nibble of the last byte is the sign, not a digit.
    digits: list[int] = []
    for i, b in enumerate(data):
        high = (b & ByteConstants.HIGH_NIBBLE_MASK) >> 4
        digits.append(high)
        if i < len(data) - 1:
            # Not the last byte: low nibble is a digit
            low = b & ByteConstants.NIBBLE_MASK
            digits.append(low)
        # Last byte: low nibble is the sign — skip it

    digit_str = "".join(str(d) for d in digits)
    int_value = int(digit_str) if digit_str else 0

    if decimal_digits > 0:
        # Build Decimal directly from integer and scale
        result = Decimal(int_value) / Decimal(10 ** decimal_digits)
        # Quantize to the correct scale to avoid floating-point noise
        quant = Decimal(10) ** -decimal_digits
        result = result.quantize(quant)
    else:
        result = Decimal(int_value)

    if negative and int_value != 0:
        result = -result

    return result


def _comp3_encode(
    value: "Decimal | int | float",
    total_digits: int,
    decimal_digits: int,
    signed: bool,
) -> bytes:
    """Encode a numeric value to COMP-3 packed BCD bytes.

    Args:
        value: Numeric value to encode.
        total_digits: Total digit positions (determines byte length).
        decimal_digits: Number of implied decimal positions.
        signed: Whether the field is signed (determines sign-nibble convention).

    Returns:
        Packed BCD bytes of length (total_digits // 2) + 1.
    """
    dec_value = Decimal(str(value))
    negative = dec_value < 0

    # Quantize to the declared scale
    if decimal_digits > 0:
        quant = Decimal(10) ** -decimal_digits
        dec_value = dec_value.quantize(quant)

    # Strip sign and decimal point; produce raw digit string
    abs_str = str(abs(dec_value))
    # Remove the decimal point if present
    if "." in abs_str:
        integer_part, frac_part = abs_str.split(".")
        # Pad fractional part to declared decimal_digits, truncate if longer
        frac_part = (frac_part + "0" * decimal_digits)[:decimal_digits]
        raw_digits = integer_part + frac_part
    else:
        raw_digits = abs_str
        if decimal_digits > 0:
            raw_digits = raw_digits + "0" * decimal_digits

    # Left-zero-pad to total_digits, truncate if too long
    raw_digits = raw_digits.zfill(total_digits)[-total_digits:]

    # Determine sign nibble
    if negative:
        sign_nibble = ByteConstants.SIGN_NIBBLE_NEGATIVE   # 0x0D
    elif signed:
        sign_nibble = ByteConstants.SIGN_NIBBLE_POSITIVE   # 0x0C
    else:
        sign_nibble = ByteConstants.SIGN_NIBBLE_UNSIGNED   # 0x0F

    # Build a nibble sequence: all digit nibbles followed by the sign nibble.
    # Total nibble count = total_digits + 1.
    # Byte count = (total_digits // 2) + 1, which gives (total_digits + 1) nibbles
    # when total_digits is odd (exact fit), or (total_digits + 2) nibbles when even
    # (one leading zero nibble is prepended to right-align the sequence).
    nibbles: list[int] = [int(ch) for ch in raw_digits]
    nibbles.append(sign_nibble)

    byte_count = (total_digits // 2) + 1
    total_nibble_slots = byte_count * 2

    # Right-align nibble sequence into the available slots (pad with 0 on the left)
    padded = [0] * (total_nibble_slots - len(nibbles)) + nibbles

    result = bytearray(byte_count)
    for i in range(byte_count):
        result[i] = (padded[2 * i] << 4) | padded[2 * i + 1]

    return bytes(result)


# ── BINARY (COMP/COMP-4) codec ───────────────────────────────────────────────


def _binary_decode(data: bytes, signed: bool) -> int:
    """Decode BINARY (COMP/COMP-4) big-endian bytes to a Python int.

    Args:
        data: Big-endian byte sequence (2, 4, or 8 bytes).
        signed: Whether the field is signed (two's complement).

    Returns:
        Decoded integer value.
    """
    if not data:
        return 0
    return int.from_bytes(data, "big", signed=signed)


def _binary_encode(value: int, length: int, signed: bool) -> bytes:
    """Encode a Python int to BINARY (COMP/COMP-4) big-endian bytes.

    Args:
        value: Integer value to encode.
        length: Byte length (2, 4, or 8 bytes).
        signed: Whether the field is signed.

    Returns:
        Big-endian byte sequence of the given length.
    """
    return value.to_bytes(length, "big", signed=signed)


# ── WS region access ─────────────────────────────────────────────────────────


def _get_ws_region(vm):
    """Return (addr, region bytearray) for the WS region, or (None, None).

    Mirrors the pattern from cicada's cics.builtins.system._get_ws_region_addr:
    walk vm.call_stack reversed and look for a local var named '__ws_region'.
    """
    try:
        call_stack = vm.call_stack
    except AttributeError:
        return None, None

    # Mirror cics.builtins.system._get_ws_region_addr EXACTLY: the real VM keys
    # frame.local_vars by VarName and keys its region map by Address. Matching on
    # a duck-typed str/.name or passing a raw-str addr silently misses both the
    # VarName equality and the Address-keyed region_get (Address.__eq__ rejects
    # bare str), so the WS region must be reached through the real value types.
    ws_var = VarName("__ws_region")
    for frame in reversed(call_stack):
        local_vars = getattr(frame, "local_vars", {})
        if ws_var in local_vars:
            tv = local_vars[ws_var]
            addr = Address(str(tv.value))
            region = vm.region_get(addr)
            if region is not None:
                return addr, region
    return None, None


def _read_field_bytes(vm, region, name: str) -> bytes | None:
    """Read raw bytes for a named field from the WS region."""
    f = vm.data_layout.get(name)
    if f is None:
        return None
    off, length = f["offset"], f["length"]
    return bytes(region[off: off + length])


def _write_field_bytes(vm, region, name: str, data: bytes) -> bool:
    """Write bytes into a named field in the WS region."""
    f = vm.data_layout.get(name)
    if f is None:
        return False
    off, length = f["offset"], f["length"]
    region[off: off + length] = data[:length]
    return True


def _decode_field(data: bytes, f: dict):
    """Decode field bytes to a Python value based on the field's category.

    Supported categories:
      ZONED_DECIMAL → int
      ALPHANUMERIC  → str
      COMP3         → Decimal
      BINARY        → int
    """
    category = f.get("category", "ALPHANUMERIC")
    if category == "ZONED_DECIMAL":
        return _zoned_decode(data)
    if category == "COMP3":
        return _comp3_decode(data, f.get("decimal_digits", 0))
    if category == "BINARY":
        return _binary_decode(data, f.get("signed", True))
    # ALPHANUMERIC (and anything else)
    return _alpha_decode(data)


def _encode_field(value, f: dict, length: int) -> bytes:
    """Encode a Python value to bytes based on the field's category.

    Supported categories:
      ZONED_DECIMAL → _zoned_encode
      ALPHANUMERIC  → _alpha_encode
      COMP3         → _comp3_encode
      BINARY        → _binary_encode
    """
    category = f.get("category", "ALPHANUMERIC")
    if category == "ZONED_DECIMAL":
        return _zoned_encode(int(value), length)
    if category == "COMP3":
        return _comp3_encode(
            value,
            f["total_digits"],
            f["decimal_digits"],
            f.get("signed", True),
        )
    if category == "BINARY":
        return _binary_encode(int(value), length, f.get("signed", True))
    return _alpha_encode(str(value), length)


# ── Public API ────────────────────────────────────────────────────────────────


def read_params(vm, in_names: tuple[str, ...]) -> list:
    """Read host-variable fields from the WS region and return as a Python list.

    ZONED_DECIMAL fields are decoded to int; ALPHANUMERIC fields to str.
    """
    _, region = _get_ws_region(vm)
    if region is None:
        return [None] * len(in_names)

    result = []
    for name in in_names:
        f = vm.data_layout.get(name)
        if f is None:
            result.append(None)
            continue
        off, length = f["offset"], f["length"]
        raw = bytes(region[off: off + length])
        result.append(_decode_field(raw, f))
    return result


def write_outputs(vm, out_names: tuple[str, ...], row: tuple) -> None:
    """Write a result row's values into WS host-variable fields.

    Each value is encoded per the field's category and written into the region.
    """
    _, region = _get_ws_region(vm)
    if region is None:
        return

    for name, value in zip(out_names, row):
        f = vm.data_layout.get(name)
        if f is None:
            continue
        length = f["length"]
        encoded = _encode_field(value, f, length)
        off = f["offset"]
        region[off: off + length] = encoded[:length]


def write_sqlcode(vm, code: int) -> None:
    """Write ``code`` into the SQLCODE field in the WS region.

    Encoding is determined by the SQLCODE field's own ``category`` in
    data_layout.  In real SQLCA the field is BINARY (PIC S9(9) COMP);
    in test fixtures it may be ZONED_DECIMAL.  Both are handled via
    ``_encode_field`` so this function stays category-agnostic.
    """
    _, region = _get_ws_region(vm)
    if region is None:
        return

    f = vm.data_layout.get("SQLCODE")
    if f is None:
        return
    length = f["length"]
    encoded = _encode_field(code, f, length)
    off = f["offset"]
    region[off: off + length] = encoded[:length]
