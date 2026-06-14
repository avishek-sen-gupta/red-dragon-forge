"""
squall.binding
~~~~~~~~~~~~~~
Dialect-agnostic bridge between COBOL host-variable fields and SQL params/results.

All functions are pure (no global mutable state). The VM interface is duck-typed:
any object with ``call_stack``, ``data_layout``, and ``region_get`` satisfies it.

Supported codec categories (slice 1):
  - ZONED_DECIMAL  (PIC 9 / S9 DISPLAY)
  - ALPHANUMERIC   (PIC X)
"""

from __future__ import annotations

import sys
import os

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
    """Decode field bytes to a Python value based on the field's category."""
    category = f.get("category", "ALPHANUMERIC")
    if category == "ZONED_DECIMAL":
        return _zoned_decode(data)
    # ALPHANUMERIC (and anything else)
    return _alpha_decode(data)


def _encode_field(value, f: dict, length: int) -> bytes:
    """Encode a Python value to bytes based on the field's category."""
    category = f.get("category", "ALPHANUMERIC")
    if category == "ZONED_DECIMAL":
        return _zoned_encode(int(value), length)
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

    SQLCODE is a signed zoned decimal field (S9(9)).
    """
    _, region = _get_ws_region(vm)
    if region is None:
        return

    f = vm.data_layout.get("SQLCODE")
    if f is None:
        return
    length = f["length"]
    encoded = _zoned_encode(code, length)
    off = f["offset"]
    region[off: off + length] = encoded[:length]
