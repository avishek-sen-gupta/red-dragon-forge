"""A 24x80 3270 screen as a table of fields, independent of any wire protocol.

Headless tests read what a program put on the screen through this model, and the
TN3270 adapter paints it. Every operation returns a new screen.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import partial, reduce
from types import MappingProxyType

from bms_copybook_gen.models import BmsField, BmsMap
from cics.bms.attributes import (
    ATTRIBUTE_BITS,
    COLOR_CODES,
    HILIGHT_CODES,
    INTENSITY_MASK,
    MDT,
    NONDISPLAY,
    PROTECTED,
    attribute_byte,
)
from cics.bms.catalog import MapCatalog
from cics.screen.cursor import CursorPosition
from cics.screen.payload import (
    NO_OVERRIDE,
    FieldAttributes,
    ScreenPayload,
    SendMapPayload,
    SendMode,
    SendTextPayload,
)

ROWS = 24
COLS = 80
BUFFER_SIZE = ROWS * COLS
_LOW_VALUE = "\x00"


class UnsupportedMapSize(ValueError):
    pass


def address(row: int, col: int) -> int:
    """Buffer offset of a 1-based (row, column)."""
    return (row - 1) * COLS + (col - 1)


@dataclass(frozen=True)
class ScreenField:
    """One field. Its attribute byte sits at ``address``; data starts one later."""

    address: int
    length: int
    name: str
    attribute: int
    color: int
    hilight: int
    content: str

    @property
    def data_address(self) -> int:
        return (self.address + 1) % BUFFER_SIZE

    @property
    def dark(self) -> bool:
        return self.attribute & INTENSITY_MASK == NONDISPLAY

    @property
    def protected(self) -> bool:
        return bool(self.attribute & PROTECTED)

    @property
    def modified(self) -> bool:
        return bool(self.attribute & MDT)

    def visible_text(self) -> str:
        return "" if self.dark else self.content[: self.length]


@dataclass(frozen=True)
class _Write:
    """One field as a send writes it. ``carries_data`` records whether the write
    put characters in the buffer at all — a field the map gave no INITIAL and the
    program did not send is an SBA/SF pair with nothing after it. Blanks ARE
    characters: a sent value of spaces (which reaches here rstripped to "")
    erases what was under it."""

    field: ScreenField
    carries_data: bool


Fields = tuple[ScreenField, ...]
Writes = tuple[_Write, ...]
FieldWriter = Callable[[Fields, SendMapPayload, BmsMap], Writes]


def _layout_field(element: BmsField) -> ScreenField:
    return ScreenField(
        address=address(element.row, element.col),
        length=element.length,
        name=element.label,
        attribute=attribute_byte(element.attrb),
        color=COLOR_CODES[element.color],
        hilight=HILIGHT_CODES[element.hilight],
        content=element.initial,
    )


def _sent(value: str) -> bool:
    """BMS sends a symbolic field only when its first byte is not low-values."""
    return not value.startswith(_LOW_VALUE)


def _with_attributes(field: ScreenField, attrs: FieldAttributes) -> ScreenField:
    return replace(
        field,
        attribute=attrs.attr & ATTRIBUTE_BITS if attrs.attr else field.attribute,
        color=attrs.color if attrs.color else field.color,
        hilight=attrs.hilight if attrs.hilight else field.hilight,
    )


def _map_default(field: ScreenField) -> _Write:
    return _Write(field, carries_data=bool(field.content))


def _with_data(field: ScreenField, payload: SendMapPayload) -> _Write:
    value = payload.fields.get(field.name, _LOW_VALUE)
    sent = _sent(value)
    content = value.replace(_LOW_VALUE, "") if sent else field.content
    attrs = payload.attrs.get(field.name, NO_OVERRIDE)
    return _Write(
        _with_attributes(replace(field, content=content), attrs),
        carries_data=sent or bool(field.content),
    )


def _maponly(_base: Fields, _payload: SendMapPayload, bms_map: BmsMap) -> Writes:
    return tuple(_map_default(_layout_field(e)) for e in bms_map.elements)


def _full(_base: Fields, payload: SendMapPayload, bms_map: BmsMap) -> Writes:
    return tuple(_with_data(_layout_field(e), payload) for e in bms_map.elements)


def _dataonly(base: Fields, payload: SendMapPayload, _bms_map: BmsMap) -> Writes:
    named = frozenset((*payload.fields, *payload.attrs))
    return tuple(_with_data(f, payload) for f in base if f.name in named)


_WRITERS: Mapping[SendMode, FieldWriter] = MappingProxyType(
    {SendMode.FULL: _full, SendMode.MAPONLY: _maponly, SendMode.DATAONLY: _dataonly}
)


def _kept_fields(fields: Fields, payload: SendMapPayload) -> Fields:
    kept = () if payload.erase else fields
    reset = tuple(replace(f, attribute=f.attribute & ~MDT) for f in kept)
    return reset if payload.frset else kept


def _over(under: ScreenField, write: _Write) -> ScreenField:
    """A write that carried no characters takes over the attribute byte and leaves
    the buffer alone. CACTVWA relies on this — COACTVW.bms declares an unlabelled
    LENGTH=9 field, with neither INITIAL nor a symbolic name, at the POS=(1,1) its
    'Tran:' caption already occupies."""
    if write.carries_data:
        return write.field
    return replace(write.field, content=under.content)


def _placed(
    by_address: Mapping[int, ScreenField], write: _Write
) -> Mapping[int, ScreenField]:
    under = by_address.get(write.field.address, write.field)
    return {**by_address, write.field.address: _over(under, write)}


def _merge(base: Fields, writes: Writes) -> Fields:
    """The screen the writes leave behind. A write owns the attribute byte at its
    address, and the characters after it only when it carried any."""
    placed = {field.address: field for field in base}
    by_address = reduce(_placed, writes, placed)
    return tuple(by_address[a] for a in sorted(by_address))


def _require_full_screen(bms_map: BmsMap) -> None:
    if bms_map.size != (ROWS, COLS):
        raise UnsupportedMapSize(
            f"map {bms_map.label} is {bms_map.size}; only 24x80 maps are modelled"
        )


def _insert_cursor(bms_map: BmsMap, fallback: int) -> int:
    """The last field with ATTRB=IC takes the cursor, as in BMS."""
    marked = tuple(
        address(e.row, e.col) + 1 for e in bms_map.elements if "IC" in e.attrb
    )
    return marked[-1] if marked else fallback


def _field_start(fields: Sequence[ScreenField], name: str) -> int:
    starts = tuple(f.data_address for f in fields if f.name == name)
    if not starts:
        raise KeyError(f"no field named {name!r} on the screen")
    return starts[0]


def _typed(field: ScreenField, values: Mapping[str, str]) -> ScreenField:
    if field.name not in values:
        return field
    return replace(field, content=values[field.name], attribute=field.attribute | MDT)


@dataclass(frozen=True)
class TerminalScreen:
    fields: Fields = ()
    unformatted: str = ""
    cursor: int = 0
    alarm: bool = False

    def apply(self, payload: SendMapPayload, bms_map: BmsMap) -> TerminalScreen:
        _require_full_screen(bms_map)
        base = _kept_fields(self.fields, payload)
        fields = _merge(base, _WRITERS[payload.mode](base, payload, bms_map))
        dataonly = payload.mode is SendMode.DATAONLY
        default = self.cursor if dataonly else _insert_cursor(bms_map, 0)
        return TerminalScreen(
            fields=fields,
            unformatted="" if payload.erase else self.unformatted,
            cursor=payload.cursor.resolve(partial(_field_start, fields), default),
            alarm=payload.alarm,
        )

    def apply_text(self, payload: SendTextPayload) -> TerminalScreen:
        return TerminalScreen(unformatted=payload.text[:BUFFER_SIZE])

    def apply_payload(
        self, payload: ScreenPayload, catalog: MapCatalog
    ) -> TerminalScreen:
        if isinstance(payload, SendTextPayload):
            return self.apply_text(payload)
        return self.apply(payload, catalog.lookup(payload.mapset, payload.map))

    def with_input(
        self, values: Mapping[str, str], cursor: CursorPosition
    ) -> TerminalScreen:
        """The screen as the operator left it: typed values, their MDTs set."""
        fields = tuple(_typed(f, values) for f in self.fields)
        at = cursor.resolve(partial(_field_start, fields), self.cursor)
        return TerminalScreen(fields, self.unformatted, at, alarm=False)

    def field(self, name: str) -> ScreenField:
        matches = tuple(f for f in self.fields if f.name == name)
        if not matches:
            raise KeyError(f"no field named {name!r} on the screen")
        return matches[0]

    def field_with_data_at(self, data_address: int) -> ScreenField:
        matches = tuple(f for f in self.fields if f.data_address == data_address)
        if not matches:
            raise KeyError(f"no field's data starts at buffer address {data_address}")
        return matches[0]

    def row(self, number: int) -> str:
        """Row ``number`` (1-based) as displayed: attribute bytes and dark
        fields show as blanks."""
        cells = self._cells()
        start = address(number, 1)
        return "".join(cells.get(start + col, " ") for col in range(COLS))

    def text(self) -> str:
        return "\n".join(self.row(number) for number in range(1, ROWS + 1))

    def _cells(self) -> Mapping[int, str]:
        typed = dict(enumerate(self.unformatted))
        painted = {
            (f.data_address + i) % BUFFER_SIZE: ch
            for f in self.fields
            for i, ch in enumerate(f.visible_text())
        }
        attribute_bytes = {f.address: " " for f in self.fields}
        return {**typed, **painted, **attribute_bytes}
