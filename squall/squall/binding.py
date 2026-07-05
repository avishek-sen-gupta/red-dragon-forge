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

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from squall.parser.sql_model import FieldMeta

# Resolve vendor path so ByteConstants can be imported without installing red-dragon
# as an editable package in every environment.
_VENDOR = os.path.join(os.path.dirname(__file__), "..", "vendor", "red-dragon")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

from interpreter.address import Address  # noqa: E402
from interpreter.cobol.cobol_constants import ByteConstants  # noqa: E402
from interpreter.var_name import VarName  # noqa: E402

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
    magnitude = int("".join(str(d) for d in digits))
    negative = sign_zone == (
        ByteConstants.SIGN_NIBBLE_NEGATIVE & ByteConstants.NIBBLE_MASK
    )
    return -magnitude if negative else magnitude


def _zoned_encode(n: int, length: int) -> bytes:
    """Encode a signed integer as ZONED_DECIMAL bytes of the given length.

    Digits are right-justified and zero-filled. Every byte uses the unsigned
    zone nibble (0xF) except the last byte, which carries the sign zone:
      negative -> 0xD; non-negative -> 0xF (unsigned/positive).
    """
    abs_digits = list(str(abs(n)).zfill(length)[-length:])  # right-justify, truncate
    result = bytearray(length)
    unsigned_zone = (
        ByteConstants.SIGN_NIBBLE_UNSIGNED & ByteConstants.NIBBLE_MASK
    ) << 4  # 0xF0
    negative_zone = (
        ByteConstants.SIGN_NIBBLE_NEGATIVE & ByteConstants.NIBBLE_MASK
    ) << 4
    for i, ch in enumerate(abs_digits):
        digit = int(ch)
        # Every byte uses the unsigned zone except the last, which carries the
        # sign zone (0xD0 negative / 0xF0 non-negative).
        zone = (
            unsigned_zone
            if i < length - 1
            else (negative_zone if n < 0 else unsigned_zone)
        )
        result[i] = zone | digit
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

    # Scale by the implied decimal point, quantizing to avoid float noise.
    magnitude = (
        (Decimal(int_value) / Decimal(10**decimal_digits)).quantize(
            Decimal(10) ** -decimal_digits
        )
        if decimal_digits > 0
        else Decimal(int_value)
    )
    return -magnitude if (negative and int_value != 0) else magnitude


def _comp3_encode(
    value: Decimal | int | float,
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
    raw_value = Decimal(str(value))
    negative = raw_value < 0  # sign taken from the value, before scale rounding
    dec_value = (
        raw_value.quantize(Decimal(10) ** -decimal_digits)
        if decimal_digits > 0
        else raw_value
    )

    # Digit string, sign and decimal point removed. partition handles the no-"."
    # case (frac == ""); the fraction is padded/truncated to the field scale and
    # the whole is left-zero-padded (or truncated) to total_digits.
    int_part, _, frac = str(abs(dec_value)).partition(".")
    digits = int_part + (frac + "0" * decimal_digits)[:decimal_digits]
    raw_digits = digits.zfill(total_digits)[-total_digits:]

    sign_nibble = (
        ByteConstants.SIGN_NIBBLE_NEGATIVE  # 0x0D
        if negative
        else (
            ByteConstants.SIGN_NIBBLE_POSITIVE  # 0x0C (signed)
            if signed
            else ByteConstants.SIGN_NIBBLE_UNSIGNED
        )  # 0x0F
    )

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


def _get_ws_region(vm) -> tuple[Address, bytearray]:
    """Return (addr, region) for the WS region, failing loudly if it is absent.

    The real VM keys frame.local_vars by VarName and its region map by Address
    (Address.__eq__ rejects a bare str), so the region must be reached through the
    real value types — mirroring cics.builtins.system._get_ws_region_addr. A
    running SQL program always has a WS region; its absence is an invariant
    violation, so we raise rather than return a sentinel for callers to absorb.
    """
    ws_var = VarName("__ws_region")
    for frame in reversed(vm.call_stack):
        local_vars = getattr(frame, "local_vars", {})
        if ws_var in local_vars:
            addr = Address(str(local_vars[ws_var].value))
            region = vm.region_get(addr)
            if region is not None:
                return addr, region
    raise LookupError("no __ws_region present in the VM call stack")


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


# ── VARCHAR (49-group) codec ──────────────────────────────────────────────────
#
# A VARCHAR host var is an IBM DCLGEN group spanning two 49-level children: a
# binary length prefix (<HV>-LEN) and the text (<HV>-TEXT). The flat data_layout
# records all three entries but cannot mark the group as VARCHAR — the dclgen
# ``field_meta`` map supplies that and names the children. The codec reads/writes
# the LEN child as binary and the first LEN characters of the TEXT child.


def _meta_for(field_meta: Mapping[str, FieldMeta], name: str) -> FieldMeta:
    """Case-insensitive lookup of a host var's dclgen metadata; ``{}`` if absent.

    Mirrors ``_lookup_field``: COBOL identifiers are case-insensitive but the
    generated metadata preserves the host-var case. Returns an empty mapping
    rather than None so callers can ``.get("category")`` unconditionally.
    """
    exact = field_meta.get(name)
    if exact is not None:
        return exact
    upper = name.upper()
    return next(
        (entry for key, entry in field_meta.items() if key.upper() == upper),
        {},
    )


def _varchar_decode(data_layout: dict, region: bytearray, meta: dict) -> str:
    """Pure: decode a VARCHAR host var to its first-LEN characters.

    Reads the binary LEN child and returns exactly that many decoded characters
    (no trailing-pad ambiguity). A well-formed VARCHAR has LEN within its TEXT
    capacity by contract; we do not defend against a corrupt LEN.
    """
    len_f = _require_field(data_layout, meta["len_var"])
    text_f = _require_field(data_layout, meta["text_var"])
    lo, ll = len_f["offset"], len_f["length"]
    n = _binary_decode(bytes(region[lo : lo + ll]), len_f.get("signed", True))
    to = text_f["offset"]
    return _alpha_decode(bytes(region[to : to + n]))


def _varchar_writes(
    value: str, data_layout: dict, meta: dict
) -> tuple[tuple[int, bytes], ...]:
    """Pure: the ``(offset, bytes)`` writes that store *value* into a VARCHAR group.

    Returns the LEN-child and TEXT-child writes; the caller applies them so the
    region mutation stays at the single boundary in ``write_outputs`` — mirroring
    how ``_encode_field`` returns bytes rather than touching the region itself.
    """
    len_f = _require_field(data_layout, meta["len_var"])
    text_f = _require_field(data_layout, meta["text_var"])
    len_bytes = _binary_encode(len(value), len_f["length"], len_f.get("signed", True))
    text_bytes = _alpha_encode(value, text_f["length"])
    return (len_f["offset"], len_bytes), (text_f["offset"], text_bytes)


# ── Coercion layer (strict) ───────────────────────────────────────────────────
#
# When a SQL value is assigned into a host variable whose COBOL type does not
# match, production DB2 applies SQL assignment rules: convert silently where
# lossless, convert-with-SQLWARN where lossy (string/fraction truncation, with
# the indicator carrying the original length), and fail with a negative SQLCODE
# only when the value cannot fit or the types are incompatible.
#
# This layer is the SEAM for that behaviour but is deliberately STRICT for now:
# any assignment that would require coercion (cross-family or lossy) returns a
# genuine-failure SQLCODE immediately and writes nothing. The tolerant
# convert-and-warn path is the branch this fills in later — tracked as squall-ud0.

SQLCODE_INCOMPATIBLE_TYPE: Final = -301  # cross-family (e.g. text → numeric host var)
SQLCODE_VALUE_OUT_OF_RANGE: Final = (
    -304
)  # numeric overflow / precision loss / truncation
SQLCODE_NULL_NO_INDICATOR: Final = (
    -305
)  # NULL fetched into a host var with no indicator

_NUMERIC_CATEGORIES: Final = frozenset({"ZONED_DECIMAL", "COMP3", "BINARY"})


def _decimal_digit_counts(dec: Decimal) -> tuple[int, int]:
    """Return (integer_digit_count, fractional_digit_count) for *dec*."""
    _, digits, exponent = dec.as_tuple()
    if not isinstance(exponent, int):  # NaN / Infinity carry a string exponent
        return 0, 0
    if exponent >= 0:
        return len(digits) + exponent, 0
    frac = -exponent
    int_digits = len(digits) - frac
    return (int_digits if int_digits > 0 else 0), frac


def _assignability(value, f: dict) -> int:
    """Return 0 if *value* can be assigned into field *f* with no coercion or
    loss, else a genuine-failure SQLCODE.

    Strict policy (tolerant convert/warn deferred — squall-ud0): any cross-family
    assignment fails with -301, any value that overflows the field or would lose
    precision/be truncated fails with -304, and a NULL into a field with no
    indicator fails with -305.
    """
    if value is None:
        return SQLCODE_NULL_NO_INDICATOR

    category = f.get("category", "ALPHANUMERIC")

    if category in _NUMERIC_CATEGORIES:
        # bool is an int subclass but is never a valid numeric SQL value here.
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            return SQLCODE_INCOMPATIBLE_TYPE
        dec = Decimal(str(value))
        if not dec.is_finite():  # NaN / Infinity can't be represented
            return SQLCODE_VALUE_OUT_OF_RANGE
        int_digits, frac_digits = _decimal_digit_counts(dec)
        decimal_digits = f.get("decimal_digits", 0)
        total_digits = f.get("total_digits", 0)
        if frac_digits > decimal_digits:
            return SQLCODE_VALUE_OUT_OF_RANGE  # would truncate fractional digits
        if int_digits > total_digits - decimal_digits:
            return SQLCODE_VALUE_OUT_OF_RANGE  # integer part overflows the field
        return 0

    # ALPHANUMERIC (character) field.
    if isinstance(value, str):
        if len(value) > f.get("length", len(value)):
            return SQLCODE_VALUE_OUT_OF_RANGE  # would truncate the string
        return 0
    # A numeric (or other) value into a character host var is not an allowed
    # assignment without an explicit cast.
    return SQLCODE_INCOMPATIBLE_TYPE


def _varchar_assignability(value, text_f: dict) -> int:
    """Strict assignability for a VARCHAR host var (its TEXT child capacity).

    A character value is required; a value longer than the declared capacity
    would truncate (-304); a non-string is cross-family (-301); NULL with no
    indicator is -305.
    """
    if value is None:
        return SQLCODE_NULL_NO_INDICATOR
    if not isinstance(value, str):
        return SQLCODE_INCOMPATIBLE_TYPE
    if len(value) > text_f["length"]:
        return SQLCODE_VALUE_OUT_OF_RANGE
    return 0


def _lookup_field(data_layout, name: str):
    """Look up a field by host-var name, CASE-INSENSITIVELY.

    COBOL identifiers are case-insensitive, but ProLeap preserves the source
    (declaration) case in ``data_layout`` — so a program that declares ``pname``
    yet writes ``FETCH … INTO :PNAME`` must still resolve. Try the exact name
    first (fast path), then fall back to an upper-cased scan.
    """
    f = data_layout.get(name)
    if f is not None:
        return f
    upper = name.upper()
    return next(
        (entry for key, entry in data_layout.items() if key.upper() == upper),
        None,
    )


def _require_field(data_layout, name: str) -> dict:
    """Resolve a field that must exist; raise loudly if it does not.

    Used where the field's presence is an invariant — e.g. the LEN/TEXT children
    of a dclgen-generated VARCHAR group. A miss is a generation/layout bug, not a
    runtime condition to absorb, so it fails rather than returning a sentinel.
    """
    f = _lookup_field(data_layout, name)
    if f is None:
        raise KeyError(f"host-var field {name!r} not found in data_layout")
    return f


class FieldMetaMismatch(Exception):
    """A dclgen sidecar's category disagrees with ProLeap's parsed data_layout —
    copybook/schema drift. Raised loud (not an SQLCODE): a generation/layout bug,
    not a runtime SQL condition."""

    def __init__(self, name: str, expected, actual) -> None:
        super().__init__(
            f"dclgen/copybook drift for {name!r}: dclgen category {expected!r} "
            f"but data_layout category {actual!r}"
        )


def _require_category(data_layout, name: str, expected: str) -> None:
    """Assert ``data_layout[name].category == expected``; raise loud otherwise.

    A missing field raises KeyError via _require_field — itself a drift signal.
    """
    actual = _require_field(data_layout, name).get("category")
    if actual != expected:
        raise FieldMetaMismatch(name, expected, actual)


def validate_field_meta(data_layout, field_meta: Mapping[str, FieldMeta]) -> None:
    """Fail loud if any dclgen field_meta category disagrees with data_layout.

    Scalars: data_layout[name].category must equal the dclgen category. VARCHAR:
    the data_layout cannot mark the 49-group, so the children are checked instead
    (len_var is BINARY, text_var is ALPHANUMERIC). Empty field_meta is a no-op.
    """
    for name, meta in field_meta.items():
        category = meta.get("category")
        if category == "VARCHAR":
            _require_category(data_layout, meta["len_var"], "BINARY")
            _require_category(data_layout, meta["text_var"], "ALPHANUMERIC")
        else:
            _require_category(data_layout, name, category)


# ── Public API ────────────────────────────────────────────────────────────────


def read_params(
    vm, in_names: tuple[str, ...], field_meta: Mapping[str, FieldMeta]
) -> list:
    """Read host-variable fields from the WS region and return as a Python list.

    ZONED_DECIMAL fields are decoded to int; ALPHANUMERIC fields to str; COMP-3 to
    Decimal; BINARY to int. A host var carrying VARCHAR dclgen *field_meta* is
    decoded through its 49-group LEN/TEXT children instead of as a flat group.
    """
    _, region = _get_ws_region(vm)
    return [_read_one(vm.data_layout, region, field_meta, name) for name in in_names]


def _read_one(
    data_layout: dict, region: bytearray, field_meta: Mapping[str, FieldMeta], name: str
):
    """Pure: decode one host var — VARCHAR via its 49-group, else its flat field."""
    meta = _meta_for(field_meta, name)
    if meta.get("category") == "VARCHAR":
        return _varchar_decode(data_layout, region, meta)
    f = _require_field(data_layout, name)
    off, length = f["offset"], f["length"]
    return _decode_field(bytes(region[off : off + length]), f)


@dataclass(frozen=True)
class _Plan:
    """A planned host-var assignment: a result SQLCODE and the writes to apply.

    ``code == 0`` means assignable, with *writes* the ``(offset, bytes)`` pairs to
    apply; a non-zero *code* is a coercion failure carrying no writes.
    """

    code: int
    writes: tuple[tuple[int, bytes], ...]


def _plan_assignment(
    data_layout: dict, field_meta: Mapping[str, FieldMeta], name: str, value
) -> _Plan:
    """Pure: plan one host-var assignment. VARCHAR host vars (carrying dclgen
    metadata) plan through their 49-group LEN/TEXT children; all others through
    their flat field.
    """
    meta = _meta_for(field_meta, name)
    if meta.get("category") == "VARCHAR":
        text_f = _require_field(data_layout, meta["text_var"])
        varchar_code = _varchar_assignability(value, text_f)
        if varchar_code != 0:
            return _Plan(varchar_code, ())
        return _Plan(0, _varchar_writes(value, data_layout, meta))

    f = _require_field(data_layout, name)
    scalar_code = _assignability(value, f)
    if scalar_code != 0:
        return _Plan(scalar_code, ())
    return _Plan(
        0, ((f["offset"], _encode_field(value, f, f["length"])[: f["length"]]),)
    )


def write_outputs(
    vm,
    out_names: tuple[str, ...],
    row: tuple,
    field_meta: Mapping[str, FieldMeta],
) -> int:
    """Assign a result row's values into WS host-variable fields.

    Returns 0 on success, or a genuine-failure SQLCODE if any value cannot be
    assigned to its host var (strict coercion — see ``_assignability``). The
    assignment is ATOMIC: every value is planned and validated first, and if any
    fails NOTHING is written (matching DB2, which fails the whole statement).

    Planning is pure (``_plan_assignment``); the only mutation is the final apply
    loop — the single sanctioned boundary at the VM memory region.
    """
    region = _get_ws_region(vm)[1]
    plans = [
        _plan_assignment(vm.data_layout, field_meta, name, value)
        for name, value in zip(out_names, row, strict=True)
    ]
    failure = next((p.code for p in plans if p.code != 0), 0)
    if failure != 0:
        return failure

    for offset, data in [write for p in plans for write in p.writes]:
        region[offset : offset + len(data)] = data
    return 0


def write_sqlcode(vm, code: int) -> None:
    """Write ``code`` into the SQLCODE field in the WS region.

    Encoding is determined by the SQLCODE field's own ``category`` in
    data_layout.  In real SQLCA the field is BINARY (PIC S9(9) COMP);
    in test fixtures it may be ZONED_DECIMAL.  Both are handled via
    ``_encode_field`` so this function stays category-agnostic.
    """
    _, region = _get_ws_region(vm)
    f = _require_field(vm.data_layout, "SQLCODE")
    length = f["length"]
    off = f["offset"]
    region[off : off + length] = _encode_field(code, f, length)[:length]
