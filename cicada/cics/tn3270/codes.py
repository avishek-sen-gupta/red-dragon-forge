"""3270 datastream and telnet constants.

3270 values follow IBM's 3270 Data Stream Programmer's Reference (GA23-0059);
telnet values follow RFC 854/855 (telnet), RFC 856 (BINARY), RFC 885 (EOR),
RFC 1091 (TERMINAL-TYPE) and RFC 1576 (TN3270).
"""

from __future__ import annotations

# Six-bit values (attribute bits, WCC bits, buffer-address halves) are sent as
# these printable EBCDIC codes.
GRAPHIC_CODES = bytes(
    (
        0x40,
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
        0x4D,
        0x4E,
        0x4F,
        0x50,
        0xD1,
        0xD2,
        0xD3,
        0xD4,
        0xD5,
        0xD6,
        0xD7,
        0xD8,
        0xD9,
        0x5A,
        0x5B,
        0x5C,
        0x5D,
        0x5E,
        0x5F,
        0x60,
        0x61,
        0xE2,
        0xE3,
        0xE4,
        0xE5,
        0xE6,
        0xE7,
        0xE8,
        0xE9,
        0x6A,
        0x6B,
        0x6C,
        0x6D,
        0x6E,
        0x6F,
        0xF0,
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
        0x7D,
        0x7E,
        0x7F,
    )
)

ERASE_WRITE = 0xF5

WCC_ALARM = 0x04
WCC_KEYBOARD_RESTORE = 0x02

ORDER_SBA = 0x11
ORDER_SF = 0x1D
ORDER_SFE = 0x29
ORDER_IC = 0x13

XA_FIELD_ATTRIBUTE = 0xC0
XA_HIGHLIGHT = 0x41
XA_FOREGROUND = 0x42

AID_CLEAR = 0x6D
AID_PA1 = 0x6C
AID_PA2 = 0x6E
AID_PA3 = 0x6B
SHORT_READ_AIDS = frozenset({AID_CLEAR, AID_PA1, AID_PA2, AID_PA3})

IAC = 255
DONT = 254
DO = 253
WONT = 252
WILL = 251
SB = 250
SE = 240
EOR = 239

OPTION_BINARY = 0
OPTION_TERMINAL_TYPE = 24
OPTION_EOR = 25

TERMINAL_TYPE_IS = 0
TERMINAL_TYPE_SEND = 1

_TWELVE_BIT_MASK = 0xC0
_SIX_BITS = 0x3F


def encode_address(offset: int) -> bytes:
    """A buffer offset as a 12-bit address, each half graphic-converted."""
    return bytes(
        (GRAPHIC_CODES[(offset >> 6) & _SIX_BITS], GRAPHIC_CODES[offset & _SIX_BITS])
    )


def decode_address(high: int, low: int) -> int:
    """12-bit addresses set either of the top two bits of the first byte; a
    14-bit address leaves both clear."""
    if high & _TWELVE_BIT_MASK:
        return ((high & _SIX_BITS) << 6) | (low & _SIX_BITS)
    return (high << 8) | low


def frame_record(data: bytes) -> bytes:
    """A 3270 record on the telnet stream: IAC bytes doubled, then IAC EOR."""
    return data.replace(bytes((IAC,)), bytes((IAC, IAC))) + bytes((IAC, EOR))
