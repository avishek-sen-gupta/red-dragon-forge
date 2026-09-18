"""Transform inbound 3270 records (operator input) into InputEvent."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from cics.dispatcher import InputEvent
from cics.screen.cursor import NO_CURSOR, Cursor, CursorPosition
from cics.screen.terminal_screen import TerminalScreen
from cics.tn3270.codes import ORDER_SBA, SHORT_READ_AIDS, decode_address

_HEADER = 3


@dataclass(frozen=True)
class Inbound:
    event: InputEvent
    # What was typed on an unformatted screen, where there are no fields to name
    # it: the transaction id and its arguments.
    unformatted_text: str


def _short_read(record: bytes) -> bool:
    return record[0] in SHORT_READ_AIDS or len(record) < _HEADER


def _cursor(record: bytes) -> CursorPosition:
    return (
        NO_CURSOR
        if _short_read(record)
        else Cursor(decode_address(record[1], record[2]))
    )


def _segments(record: bytes) -> tuple[bytes, tuple[bytes, ...]]:
    """Bytes before the first SBA order, and each SBA order's address + data."""
    leading, *ordered = record[_HEADER:].split(bytes((ORDER_SBA,)))
    return leading, tuple(ordered)


def _field_values(record: bytes, screen: TerminalScreen) -> Mapping[str, str]:
    _leading, ordered = _segments(record)
    located = (
        (screen.field_with_data_at(decode_address(s[0], s[1])), s[2:]) for s in ordered
    )
    return {field.name: data.decode("cp037") for field, data in located if field.name}


def _unformatted_text(record: bytes) -> str:
    leading, ordered = _segments(record)
    return (leading + b"".join(s[2:] for s in ordered)).decode("cp037")


def decode_inbound(record: bytes, screen: TerminalScreen) -> Inbound:
    formatted = bool(screen.fields) and not _short_read(record)
    unformatted = not screen.fields and not _short_read(record)
    event = InputEvent(
        eibaid=chr(record[0]),
        fields=_field_values(record, screen) if formatted else {},
        cursor=_cursor(record),
    )
    return Inbound(event, _unformatted_text(record) if unformatted else "")
