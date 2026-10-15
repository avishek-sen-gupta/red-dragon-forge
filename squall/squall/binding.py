"""
squall.binding
~~~~~~~~~~~~~~
Dialect-agnostic bridge between COBOL host-variable fields and SQL params/results.

All functions are pure (no global mutable state). The VM interface is duck-typed:
any object with ``call_stack``, ``declarations``, and ``region_get`` satisfies it.

Supported codec categories (slice 1 + 2):
  - ZONED_DECIMAL  (PIC 9 / S9 DISPLAY)  → int
  - ALPHANUMERIC   (PIC X)               → str
  - COMP3          (PIC S9 COMP-3)       → Decimal
  - BINARY         (PIC S9 COMP/COMP-4)  → int
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from squall.backend import SqlResult
from squall.binding_stores import apply_writes, bootstrap_vendor_path
from squall.parser.sql_model import FieldMeta, Kind

# Resolve vendor path so ByteConstants can be imported without installing red-dragon
# as an editable package in every environment.
_VENDOR = os.path.join(os.path.dirname(__file__), "..", "vendor", "red-dragon")
bootstrap_vendor_path(_VENDOR)

from interpreter.address import Address  # noqa: E402
from interpreter.cobol.cobol_constants import ByteConstants  # noqa: E402
from interpreter.cobol.field_position import FieldPosition  # noqa: E402
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
    abs_digits = str(abs(n)).zfill(length)[-length:]  # right-justify, truncate
    unsigned_zone = (
        ByteConstants.SIGN_NIBBLE_UNSIGNED & ByteConstants.NIBBLE_MASK
    ) << 4  # 0xF0
    negative_zone = (
        ByteConstants.SIGN_NIBBLE_NEGATIVE & ByteConstants.NIBBLE_MASK
    ) << 4
    # Every byte uses the unsigned zone except the last, which carries the
    # sign zone (0xD0 negative / 0xF0 non-negative).
    sign_zone = negative_zone if n < 0 else unsigned_zone
    last_index = length - 1
    return bytes(
        (sign_zone if i == last_index else unsigned_zone) | int(ch)
        for i, ch in enumerate(abs_digits)
    )


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


def _digit_nibbles(b: int, is_last_byte: bool) -> tuple[int, ...]:
    """The digit nibbles carried by one COMP-3 byte.

    Both nibbles are digits, except the low nibble of the LAST byte, which is
    the sign (not a digit) and is dropped.
    """
    high = (b & ByteConstants.HIGH_NIBBLE_MASK) >> 4
    if is_last_byte:
        return (high,)
    return (high, b & ByteConstants.NIBBLE_MASK)


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
    last_index = len(data) - 1
    digits = [d for i, b in enumerate(data) for d in _digit_nibbles(b, i == last_index)]

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


def _comp3_sign_nibble(negative: bool, signed: bool) -> int:
    """The COMP-3 sign nibble: 0x0D negative, 0x0C positive (signed), 0x0F
    unsigned."""
    if negative:
        return ByteConstants.SIGN_NIBBLE_NEGATIVE
    if signed:
        return ByteConstants.SIGN_NIBBLE_POSITIVE
    return ByteConstants.SIGN_NIBBLE_UNSIGNED


def _comp3_digit_string(
    dec_value: Decimal, total_digits: int, decimal_digits: int
) -> str:
    """The digit string (sign and decimal point removed), left-zero-padded/
    truncated to *total_digits*. ``partition`` handles the no-"." case
    (``frac == ""``); the fraction is padded/truncated to the field scale.
    """
    int_part, _, frac = str(abs(dec_value)).partition(".")
    digits = int_part + (frac + "0" * decimal_digits)[:decimal_digits]
    return digits.zfill(total_digits)[-total_digits:]


def _comp3_pack(raw_digits: str, sign_nibble: int, total_digits: int) -> bytes:
    """Pack digit nibbles + the sign nibble into COMP-3's right-aligned bytes.

    Total nibble count = total_digits + 1. Byte count = (total_digits // 2) + 1,
    which gives (total_digits + 1) nibbles when total_digits is odd (exact
    fit), or (total_digits + 2) nibbles when even (one leading zero nibble is
    prepended to right-align the sequence).
    """
    nibbles: list[int] = [int(ch) for ch in raw_digits] + [sign_nibble]
    byte_count = (total_digits // 2) + 1
    total_nibble_slots = byte_count * 2
    padded = [0] * (total_nibble_slots - len(nibbles)) + nibbles
    return bytes((padded[2 * i] << 4) | padded[2 * i + 1] for i in range(byte_count))


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
    raw_digits = _comp3_digit_string(dec_value, total_digits, decimal_digits)
    sign_nibble = _comp3_sign_nibble(negative, signed)
    return _comp3_pack(raw_digits, sign_nibble, total_digits)


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


def _resolve_ws_region(vm, frame, ws_var: VarName):
    """One call-stack frame's WS region as ``(addr, region)``, or ``()`` if this
    frame doesn't carry it (wrong frame) or the VM has no region at that
    address (stale/freed) -- an empty-tuple sentinel, not ``None``, so the
    return type carries no Optional union."""
    local_vars = getattr(frame, "local_vars", {})
    if ws_var not in local_vars:
        return ()
    addr = Address(str(local_vars[ws_var].value))
    match vm.region_get(addr):
        case None:
            return ()
        case region:
            return (addr, region)


def _get_ws_region(vm) -> tuple[Address, bytearray]:
    """Return (addr, region) for the WS region, failing loudly if it is absent.

    The real VM keys frame.local_vars by VarName and its region map by Address
    (Address.__eq__ rejects a bare str), so the region must be reached through the
    real value types — mirroring cics.builtins.system._get_ws_region_addr. A
    running SQL program always has a WS region; its absence is an invariant
    violation, so we raise rather than return a sentinel for callers to absorb.
    """
    ws_var = VarName("__ws_region")
    resolved = (
        _resolve_ws_region(vm, frame, ws_var) for frame in reversed(vm.call_stack)
    )
    match next((r for r in resolved if r), ()):
        case ():
            raise LookupError("no __ws_region present in the VM call stack")
        case (addr, region):
            return addr, region


# Category -> decoder, dispatched by table rather than an if/elif cascade
# (ALPHANUMERIC, and anything unrecognized, is the table's implicit default).
_FIELD_DECODERS: Mapping[str, Callable[..., int | str | Decimal]] = {
    "ZONED_DECIMAL": lambda data, f: _zoned_decode(data),
    "COMP3": lambda data, f: _comp3_decode(data, f.decimal_digits),
    "BINARY": lambda data, f: _binary_decode(data, f.signed),
}


def _decode_field(data: bytes, f: FieldPosition):
    """Decode field bytes to a Python value based on the field's category.

    Supported categories:
      ZONED_DECIMAL → int
      ALPHANUMERIC  → str
      COMP3         → Decimal
      BINARY        → int
    """
    category = f.category
    decoder = _FIELD_DECODERS.get(category, lambda data, f: _alpha_decode(data))
    return decoder(data, f)


# Category -> encoder, dispatched by table rather than an if/elif cascade
# (ALPHANUMERIC, and anything unrecognized, is the table's implicit default).
_FIELD_ENCODERS: Mapping[str, Callable[..., bytes]] = {
    "ZONED_DECIMAL": lambda value, f, length: _zoned_encode(int(value), length),
    "COMP3": lambda value, f, length: _comp3_encode(
        value, f.total_digits, f.decimal_digits, f.signed
    ),
    "BINARY": lambda value, f, length: _binary_encode(int(value), length, f.signed),
}


def _encode_field(value, f: FieldPosition, length: int) -> bytes:
    """Encode a Python value to bytes based on the field's category.

    Supported categories:
      ZONED_DECIMAL → _zoned_encode
      ALPHANUMERIC  → _alpha_encode
      COMP3         → _comp3_encode
      BINARY        → _binary_encode
    """
    category = f.category
    encoder = _FIELD_ENCODERS.get(
        category, lambda value, f, length: _alpha_encode(str(value), length)
    )
    return encoder(value, f, length)


# ── VARCHAR (49-group) codec ──────────────────────────────────────────────────
#
# A VARCHAR host var is an IBM DCLGEN group spanning two 49-level children: a
# binary length prefix (<HV>-LEN) and the text (<HV>-TEXT). The flat field layout
# records all three entries but cannot mark the group as VARCHAR — the dclgen
# ``field_meta`` map supplies that and names the children. The codec reads/writes
# the LEN child as binary and the first LEN characters of the TEXT child.


def _meta_for(field_meta: Mapping[str, FieldMeta], name: str) -> FieldMeta:
    """Case-insensitive lookup of a host var's dclgen metadata; ``{}`` if absent.

    Mirrors ``_lookup_field``: COBOL identifiers are case-insensitive but the
    generated metadata preserves the host-var case. Returns an empty mapping
    rather than None so callers can ``.get("category")`` unconditionally.
    """
    match field_meta.get(name):
        case None:
            upper = name.upper()
            return next(
                (entry for key, entry in field_meta.items() if key.upper() == upper),
                {},
            )
        case exact:
            return exact


def varchar_children(meta: FieldMeta) -> tuple[str, str]:
    """The (len_var, text_var) host-var names for a VARCHAR ``field_meta`` entry.

    ``FieldMeta`` is intentionally ``total=False`` -- ``len_var``/``text_var``
    apply only to the VARCHAR category. This is the one narrowing point: every
    caller here already knows ``category == "VARCHAR"``, which is exactly when
    ``dclgen_meta.py`` (Task 5) guarantees both keys are present -- narrowing
    locally keeps that contract out of ``FieldMeta``'s own shape.
    """
    match (meta.get("len_var"), meta.get("text_var")):
        case (str() as len_var, str() as text_var):
            return len_var, text_var
        case _:
            raise KeyError("VARCHAR field_meta entry missing len_var/text_var")


def _varchar_decode(
    layout: Mapping[str, FieldPosition], region: bytearray, meta: FieldMeta
) -> str:
    """Pure: decode a VARCHAR host var to its first-LEN characters.

    Reads the binary LEN child and returns exactly that many decoded characters
    (no trailing-pad ambiguity). A well-formed VARCHAR has LEN within its TEXT
    capacity by contract; we do not defend against a corrupt LEN.

    Decodes directly (NOT via ``_alpha_decode``, which rstrips): LEN already
    delimits the value exactly, so a value that legitimately ends in a space
    must keep it -- rstripping here would silently drop it.
    """
    len_var, text_var = varchar_children(meta)
    len_f = _require_field(layout, len_var)
    text_f = _require_field(layout, text_var)
    lo, ll = len_f.offset, len_f.length
    n = _binary_decode(bytes(region[lo : lo + ll]), len_f.signed)
    to = text_f.offset
    return bytes(region[to : to + n]).decode("cp037")


def _varchar_writes(
    value: str, layout: Mapping[str, FieldPosition], meta: FieldMeta
) -> tuple[tuple[int, bytes], ...]:
    """Pure: the ``(offset, bytes)`` writes that store *value* into a VARCHAR group.

    Returns the LEN-child and TEXT-child writes; the caller applies them so the
    region mutation stays at the single boundary in ``write_outputs`` — mirroring
    how ``_encode_field`` returns bytes rather than touching the region itself.
    """
    len_var, text_var = varchar_children(meta)
    len_f = _require_field(layout, len_var)
    text_f = _require_field(layout, text_var)
    len_bytes = _binary_encode(len(value), len_f.length, len_f.signed)
    text_bytes = _alpha_encode(value, text_f.length)
    return (len_f.offset, len_bytes), (text_f.offset, text_bytes)


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


def _numeric_type_ok(value) -> bool:
    """Whether *value* is a numeric SQL value's Python shape.

    bool is an int subclass but is never a valid numeric SQL value here.
    """
    return not isinstance(value, bool) and isinstance(value, (int, float, Decimal))


def _numeric_range_ok(dec: Decimal, f: FieldPosition) -> bool:
    """Whether *dec* fits field *f* without truncating a fractional digit or
    overflowing the integer part."""
    int_digits, frac_digits = _decimal_digit_counts(dec)
    decimal_digits = f.decimal_digits
    total_digits = f.total_digits
    return frac_digits <= decimal_digits and int_digits <= total_digits - decimal_digits


def _numeric_out_of_range(dec: Decimal, f: FieldPosition) -> bool:
    """NaN/Infinity can't be represented; otherwise defer to the range check."""
    if not dec.is_finite():
        return True
    return not _numeric_range_ok(dec, f)


def _numeric_assignability(value, f: FieldPosition) -> int:
    """Strict assignability for a ZONED_DECIMAL/COMP3/BINARY field."""
    if not _numeric_type_ok(value):
        return SQLCODE_INCOMPATIBLE_TYPE
    dec = Decimal(str(value))
    if _numeric_out_of_range(dec, f):
        return SQLCODE_VALUE_OUT_OF_RANGE
    return 0


def _alphanumeric_assignability(value, f: FieldPosition) -> int:
    """Strict assignability for an ALPHANUMERIC (character) field.

    A numeric (or other) value into a character host var is not an allowed
    assignment without an explicit cast.
    """
    if not isinstance(value, str):
        return SQLCODE_INCOMPATIBLE_TYPE
    if len(value) > f.length:
        return SQLCODE_VALUE_OUT_OF_RANGE  # would truncate the string
    return 0


def _assignability(value, f: FieldPosition) -> int:
    """Return 0 if *value* can be assigned into field *f* with no coercion or
    loss, else a genuine-failure SQLCODE.

    Strict policy (tolerant convert/warn deferred — squall-ud0): any cross-family
    assignment fails with -301, any value that overflows the field or would lose
    precision/be truncated fails with -304, and a NULL into a field with no
    indicator fails with -305.
    """
    match value:
        case None:
            return SQLCODE_NULL_NO_INDICATOR
        case _ if f.category in _NUMERIC_CATEGORIES:
            return _numeric_assignability(value, f)
        case _:
            return _alphanumeric_assignability(value, f)


def _varchar_string_assignability(value: str, text_f: FieldPosition) -> int:
    """A string value's assignability (the ``case str()`` arm): truncation
    only, since it's already known to be character data."""
    if len(value) > text_f.length:
        return SQLCODE_VALUE_OUT_OF_RANGE
    return 0


def _varchar_assignability(value, text_f: FieldPosition) -> int:
    """Strict assignability for a VARCHAR host var (its TEXT child capacity).

    A character value is required; a value longer than the declared capacity
    would truncate (-304); a non-string is cross-family (-301); NULL with no
    indicator is -305.
    """
    match value:
        case None:
            return SQLCODE_NULL_NO_INDICATOR
        case str():
            return _varchar_string_assignability(value, text_f)
        case _:
            return SQLCODE_INCOMPATIBLE_TYPE


def _lookup_field(layout: Mapping[str, FieldPosition], name: str):
    """Look up a field by host-var name, CASE-INSENSITIVELY.

    COBOL identifiers are case-insensitive, but ProLeap preserves the source
    (declaration) case in the field layout — so a program that declares ``pname``
    yet writes ``FETCH … INTO :PNAME`` must still resolve. Try the exact name
    first (fast path), then fall back to an upper-cased scan.
    """
    match layout.get(name):
        case None:
            upper = name.upper()
            return next(
                (entry for key, entry in layout.items() if key.upper() == upper),
                None,
            )
        case f:
            return f


def _require_field(layout: Mapping[str, FieldPosition], name: str) -> FieldPosition:
    """Resolve a field that must exist; raise loudly if it does not.

    Used where the field's presence is an invariant — e.g. the LEN/TEXT children
    of a dclgen-generated VARCHAR group. A miss is a generation/layout bug, not a
    runtime condition to absorb, so it fails rather than returning a sentinel.
    """
    match _lookup_field(layout, name):
        case None:
            raise KeyError(f"host-var field {name!r} not found in the field layout")
        case f:
            return f


# ── Public API ────────────────────────────────────────────────────────────────


def read_params(
    vm,
    layout: Mapping[str, FieldPosition],
    in_names: tuple[str, ...],
    field_meta: Mapping[str, FieldMeta],
    *,
    tolerant: bool = False,
) -> list:
    """Read host-variable fields from the WS region and return as a Python list.

    ZONED_DECIMAL fields are decoded to int; ALPHANUMERIC fields to str; COMP-3 to
    Decimal; BINARY to int. A host var carrying VARCHAR dclgen *field_meta* is
    decoded through its 49-group LEN/TEXT children instead of as a flat group.

    ``tolerant=True``: return ``None`` for any host var whose field is not found in
    the field layout rather than raising. The backend receives ``None`` for that
    parameter position; mock backends that ignore params are unaffected.
    """
    _, region = _get_ws_region(vm)
    return [
        _read_one(
            layout,
            region,
            field_meta,
            name,
            tolerant=tolerant,
        )
        for name in in_names
    ]


def _read_one(
    layout: Mapping[str, FieldPosition],
    region: bytearray,
    field_meta: Mapping[str, FieldMeta],
    name: str,
    *,
    tolerant: bool = False,
):
    """Pure: decode one host var — VARCHAR via its 49-group, else its flat field."""
    meta = _meta_for(field_meta, name)
    if meta.get("category") == "VARCHAR":
        return _varchar_decode(layout, region, meta)
    f = _lookup_field(layout, name) if tolerant else _require_field(layout, name)
    match f:
        case None:
            import logging as _logging

            _logging.getLogger(__name__).warning(
                "read_params: field %r not in the field layout — returning None", name
            )
            return None
        case _:
            off, length = f.offset, f.length
            return _decode_field(bytes(region[off : off + length]), f)


@dataclass(frozen=True)
class _Plan:
    """A planned host-var assignment: a result SQLCODE and the writes to apply.

    ``code == 0`` means assignable, with *writes* the ``(offset, bytes)`` pairs to
    apply; a non-zero *code* is a coercion failure carrying no writes.
    """

    code: int
    writes: tuple[tuple[int, bytes], ...]


def _plan_varchar_assignment(
    layout: Mapping[str, FieldPosition], meta: FieldMeta, value
) -> _Plan:
    """Pure: plan a VARCHAR host-var assignment through its 49-group children."""
    _, text_var = varchar_children(meta)
    text_f = _require_field(layout, text_var)
    varchar_code = _varchar_assignability(value, text_f)
    if varchar_code != 0:
        return _Plan(varchar_code, ())
    return _Plan(0, _varchar_writes(value, layout, meta))


def _plan_scalar_assignment(
    layout: Mapping[str, FieldPosition], name: str, value
) -> _Plan:
    """Pure: plan a non-VARCHAR host-var assignment through its flat field."""
    f = _require_field(layout, name)
    scalar_code = _assignability(value, f)
    if scalar_code != 0:
        return _Plan(scalar_code, ())
    return _Plan(0, ((f.offset, _encode_field(value, f, f.length)[: f.length]),))


def _plan_assignment(
    layout: Mapping[str, FieldPosition],
    field_meta: Mapping[str, FieldMeta],
    name: str,
    value,
) -> _Plan:
    """Pure: plan one host-var assignment. VARCHAR host vars (carrying dclgen
    metadata) plan through their 49-group LEN/TEXT children; all others through
    their flat field.
    """
    meta = _meta_for(field_meta, name)
    match meta.get("category"):
        case "VARCHAR":
            return _plan_varchar_assignment(layout, meta, value)
        case _:
            return _plan_scalar_assignment(layout, name, value)


def write_outputs(
    vm,
    layout: Mapping[str, FieldPosition],
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
        _plan_assignment(layout, field_meta, name, value)
        for name, value in zip(out_names, row, strict=True)
    ]
    failure = next((p.code for p in plans if p.code != 0), 0)
    if failure != 0:
        return failure

    apply_writes(region, tuple(write for p in plans for write in p.writes))
    return 0


def write_sqlcode(
    vm, layout: Mapping[str, FieldPosition], code: int, message: str = ""
) -> None:
    """Write ``code`` into SQLCODE, and *message* into SQLERRM, in the WS region.

    Encoding is determined by the SQLCODE field's own ``category`` in
    the field layout.  In real SQLCA the field is BINARY (PIC S9(9) COMP);
    in test fixtures it may be ZONED_DECIMAL.  Both are handled via
    ``_encode_field`` so this function stays category-agnostic.

    SQLERRM is written only when the WS region carries the standard SQLCA
    SQLERRML/SQLERRMC 49-group (looked up, not required) -- most binding
    test fixtures only lay out SQLCODE, and must keep working unchanged.
    """
    _, region = _get_ws_region(vm)
    f = _require_field(layout, "SQLCODE")
    length = f.length
    off = f.offset
    sqlcode_write = ((off, _encode_field(code, f, length)[:length]),)
    apply_writes(region, sqlcode_write + _sqlerrm_writes(layout, message))


# Real DB2 fills SQLERRM with positional substitution tokens (table/object
# names, etc.), not prose. These CardDemo programs only ever STRING SQLERRM
# into an operator-facing message and branch on nothing inside it, so this
# runtime deliberately writes the driver's own prose error text instead --
# strictly more useful to a human than a token list would be here.
def _sqlerrm_field_writes(
    len_f: FieldPosition, text_f: FieldPosition, message: str
) -> tuple[tuple[int, bytes], ...]:
    """Pure: the LEN/TEXT writes for *message*, once both SQLCA fields are
    known to be present."""
    truncated = message[: text_f.length]
    len_bytes = _binary_encode(len(truncated), len_f.length, len_f.signed)
    text_bytes = _alpha_encode(truncated, text_f.length)
    return (len_f.offset, len_bytes), (text_f.offset, text_bytes)


def _sqlca_errm_fields(layout: Mapping[str, FieldPosition]):
    """Both SQLCA SQLERRM fields as ``(len_f, text_f)``, or ``()`` if either is
    absent from *layout* (most unit-test fixtures lay out only SQLCODE)."""
    match (
        _lookup_field(layout, "SQLERRML"),
        _lookup_field(layout, "SQLERRMC"),
    ):
        case (None, _) | (_, None):
            return ()
        case (len_f, text_f):
            return (len_f, text_f)


def _sqlerrm_writes(
    layout: Mapping[str, FieldPosition], message: str
) -> tuple[tuple[int, bytes], ...]:
    """Pure: the writes that store *message* into the SQLCA SQLERRM VARCHAR
    group (SQLERRML/SQLERRMC).

    Real Db2 resets SQLCA on every statement, so an EMPTY *message* still
    writes -- it BLANKS SQLERRM (LEN 0, TEXT all spaces) rather than leaving
    a previous statement's error text in place. Without this, a statement
    that fails with driver text, followed by one that fails with none (or
    succeeds), would still show the operator the earlier error's prose.
    Returns ``()`` only when the WS region has no SQLCA at all (most
    unit-test fixtures lay out only SQLCODE).
    """
    match _sqlca_errm_fields(layout):
        case ():
            return ()
        case (len_f, text_f):
            return _sqlerrm_field_writes(len_f, text_f, message)


# Db2 reports SQLCODE +100 when an UPDATE/DELETE/INSERT (or a MERGE, or a
# dynamic EXECUTE of one of those) affects zero rows. Restricted to these
# kinds, not a blanket "rowcount == 0" check, because a backend cannot infer
# "zero rows" from rowcount alone -- DDL (e.g. CREATE, lowered as
# Kind.GENERIC) legitimately reports rowcount -1, "not applicable".
#
# MERGE and EXECUTE are included alongside INSERT/UPDATE/DELETE: real Db2
# applies the same +100 convention to a zero-row MERGE, and EXECUTE runs a
# previously-PREPAREd dynamic statement whose underlying operation is exactly
# one of these (a plain SELECT has no EXECUTE form -- it needs a cursor, or
# EXECUTE ... INTO, which already carries its own rows/sqlcode from the
# backend's result-set branch and never reaches this rowcount==0/sqlcode==0
# guard in the first place). The guard itself stays the real safety net for
# every kind: it only ever fires when sqlcode is ALREADY 0, which the
# backends set only on their non-result-set (DML) branch -- a result-set
# statement with zero rows gets sqlcode 100 from the backend directly.
_ZERO_ROW_SQLCODE_100_KINDS = frozenset(
    {Kind.INSERT, Kind.UPDATE, Kind.DELETE, Kind.MERGE, Kind.EXECUTE}
)


def resolve_dml_sqlcode(kind: Kind, result: SqlResult) -> int:
    """The SQLCODE to report for one executed DML statement.

    Db2-faithful: a zero-row UPDATE/DELETE/INSERT/MERGE/EXECUTE is +100, not
    0 -- the backend's own ``result.sqlcode`` is left untouched for every
    other kind (SELECT_INTO is bound separately; GENERIC/DDL etc. pass
    through).
    """
    if (
        kind in _ZERO_ROW_SQLCODE_100_KINDS
        and result.sqlcode == 0
        and result.rowcount == 0
    ):
        return 100
    return result.sqlcode
