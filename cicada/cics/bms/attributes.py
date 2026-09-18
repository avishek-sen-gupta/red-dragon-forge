"""BMS field attributes as 3270 values: the field attribute's six significant bits
(before graphic conversion) and the extended colour and highlight codes."""

from __future__ import annotations

from collections.abc import Collection, Mapping

MDT = 0x01
NUMERIC = 0x10
PROTECTED = 0x20
INTENSITY_MASK = 0x0C
NONDISPLAY = 0x0C
BRT = 0x08
ATTRIBUTE_BITS = 0x3F

_ASKIP = PROTECTED | NUMERIC
_PROTECTION = (("ASKIP", _ASKIP), ("PROT", PROTECTED), ("UNPROT", 0x00))
_INTENSITY = (("DRK", NONDISPLAY), ("BRT", BRT), ("DET", 0x04))

COLOR_CODES: Mapping[str, int] = {
    "": 0x00,
    "DEFAULT": 0x00,
    "BLUE": 0xF1,
    "RED": 0xF2,
    "PINK": 0xF3,
    "GREEN": 0xF4,
    "TURQUOISE": 0xF5,
    "YELLOW": 0xF6,
    "NEUTRAL": 0xF7,
}

HILIGHT_CODES: Mapping[str, int] = {
    "": 0x00,
    "OFF": 0xF0,
    "BLINK": 0xF1,
    "REVERSE": 0xF2,
    "UNDERLINE": 0xF4,
}


def _first(
    table: tuple[tuple[str, int], ...], flags: frozenset[str], default: int
) -> int:
    return next((bits for name, bits in table if name in flags), default)


def attribute_byte(attrb: Collection[str]) -> int:
    """ATTRB keywords -> the 3270 field attribute. BMS defaults protection to
    ASKIP and intensity to NORM; IC places the cursor and sets no bit."""
    flags = frozenset(attrb)
    numeric = NUMERIC if "NUM" in flags else 0
    mdt = MDT if "FSET" in flags else 0
    protection = _first(_PROTECTION, flags, _ASKIP)
    return protection | numeric | _first(_INTENSITY, flags, 0) | mdt
