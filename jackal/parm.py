"""Build the OS halfword-prefixed PARM region for COBOL LINKAGE injection."""

from __future__ import annotations

import struct


def build_parm_region(parm: str) -> bytes:
    if len(parm) > 0x7FFF:
        raise ValueError(
            f"PARM too long: {len(parm)} bytes > 32767 (signed halfword max)"
        )
    return struct.pack(">H", len(parm)) + parm.encode("latin-1")
