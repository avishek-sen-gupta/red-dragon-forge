"""The bytes an INITIALIZE operand sets: its elementary items less those the statement skips."""

from __future__ import annotations

from collections.abc import Mapping
from functools import reduce

from cobble.dataflow.fields.extent import CellIndex
from cobble.dataflow.layout import Cell
from cobol_asg.ref_mod import RefModOperand
from cobol_memory.field_extent import FieldExtent, Precision

_Run = tuple[int, int]


def initialized_extents(
    operand: RefModOperand, extent: FieldExtent, index: CellIndex
) -> tuple[FieldExtent, ...]:
    """``extent``'s bytes that INITIALIZE writes, as contiguous runs.

    Enterprise COBOL's INITIALIZE rules, 1a: without the FILLER phrase an elementary
    FILLER item is not a receiving operand, nor is an item that redefines or lies
    under a redefinition below the operand; the operand may itself redefine. Only
    the operand's own descendants count, so another record over the same bytes --
    an 01 REDEFINES -- is not written through it.

    An extent that is not one of the operand's cells -- a reference-modified slice,
    a computed subscript's span -- is written whole, as before.
    """
    owners = tuple(
        cell
        for cell in index.cells_named(
            operand.name, operand.qualifiers, len(operand.subscripts)
        )
        if _same_bytes(index.extent_of(cell), extent)
    )
    if extent.precision is not Precision.EXACT or not owners:
        return (extent,)
    owner = owners[0]
    inside = {
        cell.ordinal: cell
        for cell in index.within(extent)
        if cell.record == owner.record
    }
    runs = reduce(
        _joined,
        sorted(
            (placed.start, placed.end)
            for cell in inside.values()
            if not cell.is_group and _set(cell, owner, inside)
            for placed in (index.extent_of(cell),)
        ),
        (),
    )
    return tuple(
        FieldExtent(extent.region, start, end - start, Precision.EXACT, owner.name)
        for start, end in runs
    )


def _same_bytes(one: FieldExtent, other: FieldExtent) -> bool:
    return (one.region, one.start, one.length) == (
        other.region,
        other.start,
        other.length,
    )


def _set(cell: Cell, owner: Cell, inside: Mapping[int, Cell]) -> bool:
    if cell.ordinal == owner.ordinal:
        return True
    return not cell.filler and _below(cell, owner, inside)


def _below(cell: Cell, owner: Cell, inside: Mapping[int, Cell]) -> bool:
    if cell.ordinal == owner.ordinal:
        return True
    if cell.redefines or cell.parent not in inside:
        return False
    return _below(inside[cell.parent], owner, inside)


def _joined(runs: tuple[_Run, ...], run: _Run) -> tuple[_Run, ...]:
    if runs and run[0] <= runs[-1][1]:
        return (*runs[:-1], (runs[-1][0], max(runs[-1][1], run[1])))
    return (*runs, run)
