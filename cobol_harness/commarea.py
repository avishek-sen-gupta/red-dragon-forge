"""Commarea byte-buffer construction: given a compiled program's field
positions (field name -> FieldPosition), build a COMMAREA buffer with
specific fields overridden at their correct byte position, leaving
everything else at a fill value.  Agnostic to any one program -- every
offset is resolved by field name, never hand-computed.
"""
from __future__ import annotations

from typing import Mapping

from interpreter.cobol.field_position import FieldPosition

from .vsam import to_ebcdic

EBCDIC_SPACE = b"\x40"


def build_commarea(
    positions: Mapping[str, FieldPosition],
    group_name: str,
    length: int,
    overrides: Mapping[str, str],
    *,
    fill: bytes = EBCDIC_SPACE,
) -> bytes:
    """Build a ``length``-byte buffer, filled with ``fill`` (default EBCDIC
    space -- RedDragon's COBOL VM is EBCDIC-internal, so an ASCII-filled
    commarea silently mismatches any field it's later compared against),
    with each ``overrides`` field written at its position RELATIVE to
    ``group_name``'s own offset (so the buffer can start at 0 regardless of
    where the group happens to sit in the full WORKING-STORAGE layout).

    ``overrides`` values are plain ASCII strings; each is EBCDIC-encoded
    and truncated/left to the target field's own declared length.

    Raises KeyError if ``group_name`` or any override field name isn't in
    ``positions`` -- fields must be looked up by their COBOL name, not
    guessed, since COBOL groups commonly have gaps (FILLERs) between named
    fields.
    """
    if len(fill) != 1:
        raise ValueError("fill must be exactly one byte")
    buf = bytearray(fill * length)
    grp = positions[group_name]
    for field_name, value in overrides.items():
        fld = positions[field_name]
        rel = fld.offset - grp.offset
        if rel < 0 or rel + fld.length > length:
            raise ValueError(
                f"{field_name!r} (relative offset {rel}, length {fld.length}) "
                f"doesn't fit in a {length}-byte buffer for group {group_name!r}"
            )
        encoded = to_ebcdic(value)[: fld.length]
        buf[rel : rel + len(encoded)] = encoded
    return bytes(buf)
