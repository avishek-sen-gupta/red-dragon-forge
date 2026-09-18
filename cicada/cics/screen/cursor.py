"""Where the 3270 cursor is: a buffer offset, the first data position of a named
field (BMS symbolic cursor positioning, ``<f>L = -1`` with a bare CURSOR), or
nowhere in particular."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

CursorMessage = Mapping[str, str | int]
FieldStart = Callable[[str], int]


@dataclass(frozen=True)
class Cursor:
    offset: int

    def to_message(self) -> CursorMessage:
        return {"kind": "offset", "at": self.offset}

    def resolve(self, field_start: FieldStart, default: int) -> int:
        return self.offset

    def eibcposn(self) -> int:
        return self.offset


@dataclass(frozen=True)
class SymbolicCursor:
    field: str

    def to_message(self) -> CursorMessage:
        return {"kind": "symbolic", "field": self.field}

    def resolve(self, field_start: FieldStart, default: int) -> int:
        return field_start(self.field)

    def eibcposn(self) -> int:
        return 0


@dataclass(frozen=True)
class NoCursor:
    def to_message(self) -> CursorMessage:
        return {"kind": "none"}

    def resolve(self, field_start: FieldStart, default: int) -> int:
        return default

    def eibcposn(self) -> int:
        return 0


CursorPosition = Cursor | SymbolicCursor | NoCursor
NO_CURSOR = NoCursor()


def _offset(message: CursorMessage) -> CursorPosition:
    return Cursor(int(message["at"]))


def _symbolic(message: CursorMessage) -> CursorPosition:
    return SymbolicCursor(str(message["field"]))


def _none(_message: CursorMessage) -> CursorPosition:
    return NO_CURSOR


_READERS: Mapping[str, Callable[[CursorMessage], CursorPosition]] = {
    "offset": _offset,
    "symbolic": _symbolic,
    "none": _none,
}


def cursor_from_message(message: CursorMessage) -> CursorPosition:
    return _READERS[str(message["kind"])](message)
