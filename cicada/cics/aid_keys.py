"""The attention keys HANDLE AID names: each one's slot in DFH-AID-HANDLER and the EIBAID byte it arrives as."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

ENTER = "ENTER"
ANYKEY = "ANYKEY"

_PF_BYTES = (
    0xF1,
    0xF2,
    0xF3,
    0xF4,
    0xF5,
    0xF6,
    0xF7,
    0xF8,
    0xF9,
    0x7A,
    0x7B,
    0x7C,
    0xC1,
    0xC2,
    0xC3,
    0xC4,
    0xC5,
    0xC6,
    0xC7,
    0xC8,
    0xC9,
    0x4A,
    0x4B,
    0x4C,
)

AID_BYTES: Mapping[str, int] = MappingProxyType(
    {
        ENTER: 0x7D,
        "CLEAR": 0x6D,
        "PA1": 0x6C,
        "PA2": 0x6E,
        "PA3": 0x6B,
        **{f"PF{number}": byte for number, byte in enumerate(_PF_BYTES, start=1)},
    }
)

AID_SLOTS: Mapping[str, int] = MappingProxyType(
    {
        **{key: slot for slot, key in enumerate(AID_BYTES, start=1)},
        ANYKEY: len(AID_BYTES) + 1,
    }
)
