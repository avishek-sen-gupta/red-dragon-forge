"""Build the OS halfword-prefixed PARM region for COBOL LINKAGE injection."""

from __future__ import annotations

import struct

from interpreter.cobol.ebcdic_table import EbcdicTable


def build_parm_region(parm: str) -> bytes:
    """Return the 2-byte big-endian length prefix followed by the PARM bytes.

    The PARM bytes are encoded as EBCDIC because the red-dragon COBOL interpreter
    stores PIC X fields as EBCDIC bytes internally and decodes them with
    ``__bytes_to_string ebcdic`` when comparing or displaying character data.
    """
    if len(parm) > 0x7FFF:
        raise ValueError(
            f"PARM too long: {len(parm)} bytes > 32767 (signed halfword max)"
        )
    return struct.pack(">H", len(parm)) + EbcdicTable.ascii_to_ebcdic(
        parm.encode("ascii")
    )
