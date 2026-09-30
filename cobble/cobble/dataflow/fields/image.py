"""The bytes a program's WORKING-STORAGE holds before any statement runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import groupby
from operator import itemgetter
from types import MappingProxyType

from cobble.dataflow.fields.extent import CellIndex
from cobble.dataflow.fields.values import ValueSet, bounded, fitted
from cobble.dataflow.layout import Cell, Record
from cobol_memory.field_extent import FieldExtent

WORKING_STORAGE = "WORKING-STORAGE"

_FIGURATIVE = MappingProxyType(
    {
        "SPACE": b" ",
        "SPACES": b" ",
        "ZERO": b"0",
        "ZEROS": b"0",
        "ZEROES": b"0",
        "LOW-VALUE": b"\x00",
        "LOW-VALUES": b"\x00",
        "HIGH-VALUE": b"\xff",
        "HIGH-VALUES": b"\xff",
        "QUOTE": b'"',
        "QUOTES": b'"',
        "NULL": b"\x00",
        "NULLS": b"\x00",
    }
)


def _unquoted(text: str) -> str:
    """A literal without its surrounding quotes, its own spaces untouched.

    The bridge already strips them, so this is for a value that arrived any other
    way. Stripping whitespace instead would corrupt a declared value whose content
    is spaces -- VALUE 'USRSEC  ' is eight bytes and six of them matter.
    """
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    return text


def _literal_bytes(cell: Cell) -> bytes:
    """One cell's declared content as bytes, figurative constants included.

    A figurative constant is concrete storage -- SPACES is X'40' repeated to the
    field's width -- so excluding it would make the image claim a field holds
    nothing when the program can read eight spaces out of it and branch on them,
    which COMEN01C.cbl:198 does.
    """
    if cell.value_is_figurative:
        return _FIGURATIVE.get(cell.value.strip().upper(), b" ") * cell.length
    return _unquoted(cell.value).encode("utf-8", errors="replace")


def initial_image(
    records: Sequence[Record], index: CellIndex
) -> Mapping[FieldExtent, ValueSet]:
    """One value per elementary WORKING-STORAGE cell that declares a VALUE.

    WORKING-STORAGE only: LINKAGE and the FILE section have no initial content, and
    an extent in either with no writer in this member is exactly what
    INBOUND_LINKAGE and FROM_FILE report.

    Groups are excluded. A group's extent contains its children's, so an entry on
    the group would also be returned by ``may_alias`` for a read of any child --
    handing a caller the whole record's bytes where it asked for eight.
    """
    entries = tuple(
        (
            str(index.extent_of(cell)),
            index.extent_of(cell),
            fitted(_literal_bytes(cell), cell.length),
        )
        for record in records
        if record.origin == WORKING_STORAGE
        for cell in record.cells
        if cell.value and not cell.is_group
    )
    addressed = {name: extent for name, extent, _ in entries}
    pairs = sorted((name, value) for name, _, value in entries)
    return MappingProxyType(
        {
            addressed[name]: bounded(
                frozenset(value for _, value in group), frozenset()
            )
            for name, group in groupby(pairs, itemgetter(0))
        }
    )
