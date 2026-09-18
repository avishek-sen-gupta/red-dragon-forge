"""TerminalScreen -> an outbound 3270 record."""

from __future__ import annotations

from cics.screen.terminal_screen import ScreenField, TerminalScreen
from cics.tn3270.codes import (
    ERASE_WRITE,
    GRAPHIC_CODES,
    ORDER_IC,
    ORDER_SBA,
    ORDER_SF,
    ORDER_SFE,
    WCC_ALARM,
    WCC_KEYBOARD_RESTORE,
    XA_FIELD_ATTRIBUTE,
    XA_FOREGROUND,
    XA_HIGHLIGHT,
    encode_address,
)


def _ebcdic(text: str) -> bytes:
    return text.encode("cp037", errors="replace")


def _set_address(offset: int) -> bytes:
    return bytes((ORDER_SBA,)) + encode_address(offset)


def _start_field(field: ScreenField, extended: bool) -> bytes:
    attribute = GRAPHIC_CODES[field.attribute]
    if not extended:
        return bytes((ORDER_SF, attribute))
    pairs = (XA_FIELD_ATTRIBUTE, attribute, XA_HIGHLIGHT, field.hilight)
    return bytes((ORDER_SFE, 3, *pairs, XA_FOREGROUND, field.color))


def _field(field: ScreenField, extended: bool) -> bytes:
    content = _ebcdic(field.content[: field.length])
    return _set_address(field.address) + _start_field(field, extended) + content


def _unformatted(screen: TerminalScreen) -> bytes:
    return _set_address(0) + _ebcdic(screen.unformatted) if screen.unformatted else b""


def _wcc(screen: TerminalScreen) -> int:
    alarm = WCC_ALARM if screen.alarm else 0
    return GRAPHIC_CODES[WCC_KEYBOARD_RESTORE | alarm]


def encode_screen(screen: TerminalScreen, extended: bool) -> bytes:
    """An Erase/Write of the whole modelled screen, keyboard unlocked.

    The model already holds what the operator typed (``TerminalScreen.with_input``),
    so repainting everything loses nothing a partial Write would have kept, and
    Erase/Write puts any terminal model back to its 24x80 default size."""
    fields = b"".join(_field(f, extended) for f in screen.fields)
    cursor = _set_address(screen.cursor) + bytes((ORDER_IC,))
    return bytes((ERASE_WRITE, _wcc(screen))) + _unformatted(screen) + fields + cursor
