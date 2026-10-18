"""Pins every DFHBMSCA runtime attribute-override constant to its meaning in
cics.bms.attributes' bit names.

These bytes are what COBOL programs MOVE onto a symbolic map's "-A" field at
runtime (e.g. COACTUPC/COCRDUPC's own SETUP-SCREEN-ATTRS paragraphs) to
protect, unprotect, or force-transmit a field on the next SEND MAP.
cics.screen.terminal_screen applies ``attrs.attr & ATTRIBUTE_BITS`` to any such
override, so only the low 6 bits matter -- and they must mean what
cics.bms.attributes says PROTECTED/NUMERIC/MDT/intensity mean, or a COBOL
program's own protect/force logic silently does the wrong thing (as DFHBMPRF
and DFHBMFSE once did: named "force", but neither raw byte carried the MDT bit
cicada's own scheme uses to force it -- see forge-1zu.3 task-C-report.md).

DFHBMPRO/DFHBMPRF are real IBM DFHBMSCA values (X'60'/X'61'), which happen to
mask to bare PROTECTED / PROTECTED|MDT under cicada's scheme -- not ASKIP. An
earlier pass here suspected that combination of silently dropping a
protected field's on-screen CONTENT (not just its editability); a byte-level
diff of the actual outbound 3270 record with PRO/PRF masking to ASKIP versus
to bare PROTECTED showed the two records identical except for the attribute
bytes themselves (see forge-1zu.7, closed with that finding) -- the
screen-model/encoder path never drops content either way, so PRO/PRF use
their real, faithful values here.
"""

from __future__ import annotations

import re
from pathlib import Path

from cics.bms.attributes import (
    ATTRIBUTE_BITS,
    BRT,
    MDT,
    NONDISPLAY,
    NUMERIC,
    PROTECTED,
)
from tests.covers import NotLanguageFeature, covers

_COPYBOOK = Path(__file__).parents[3] / "cics" / "copybooks" / "DFHBMSCA.cpy"

_ASKIP = PROTECTED | NUMERIC
_DRK = NONDISPLAY

# name -> the raw-bit meaning it must decode to, spelled out in
# cics.bms.attributes' own vocabulary rather than a bare hex literal.
_EXPECTED = {
    "DFHBMPEM": 0x00,  # unprotected, normal, not forced -- unused by CardDemo
    "DFHBMPRO": PROTECTED,  # protected, not forced (real IBM X'60')
    "DFHBMPRF": PROTECTED | MDT,  # "PRotected Force" (real IBM X'61')
    "DFHBMASB": _ASKIP | BRT,  # autoskip, bright
    "DFHBMASK": _ASKIP,  # autoskip, not forced -- unused by CardDemo
    "DFHBMASF": _ASKIP | MDT,  # autoskip, MDT forced
    "DFHBMFSE": MDT,  # "Force SEt": unprotected, MDT forced
    "DFHBMDAR": _DRK,
    "DFHBMBRY": BRT,
}


def _raw_bytes() -> dict[str, int]:
    text = _COPYBOOK.read_text(encoding="utf-8")
    pattern = r"02\s+(DFHBM\w+)\s+PIC X VALUE X'([0-9A-F]{2})'"
    return {name: int(hexval, 16) for name, hexval in re.findall(pattern, text)}


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_every_constant_is_pinned():
    raw = _raw_bytes()
    assert set(raw) == set(_EXPECTED), "a DFHBMSCA constant was added/removed"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_each_constant_decodes_to_its_documented_meaning():
    raw = _raw_bytes()
    for name, expected in _EXPECTED.items():
        decoded = raw[name] & ATTRIBUTE_BITS
        assert decoded == expected, (
            f"{name} = X'{raw[name]:02X}' masks to {decoded:#04x}, "
            f"expected {expected:#04x}"
        )
