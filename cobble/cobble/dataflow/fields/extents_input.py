"""The extents table read back as the records it was written from.

``emit_extents`` lays a member's DATA DIVISION out once and publishes every cell
of it; a stage that needs the same records has no reason to lay them out again. It
reads them here instead, and the index over them comes from ``cell_index`` exactly
as it does for records built from an ASG -- one construction path, so a layout
read from the table and one computed from the cache cannot disagree.

A row's columns are arrays parallel to ``extents``, one entry per occurrence, so a
cell is a position across all of them rather than an object of its own. Position
is also all that relates them: entry ``n`` of every column belongs to the cell
whose extent is entry ``n`` of ``extents``.

Rows carry the member ``emit_extents`` read, which is what a caller naming a
member has. An older artefact, written before the columns existed, carries no
``program`` and no cells, so every member reads as absent -- which is the answer
wanted there: the file predates what is being asked of it, and saying so beats
rebuilding a layout from a table that does not hold one.

One member at a time, never the table: 29 members' cells are 1.5GB of objects
once built, and the 300-member corpus this is meant for would be fifteen times
that. A caller takes one member's layout, analyses it and drops it, so the peak is
the largest member's records and not the corpus's. A member's rows are consecutive
-- both producers write member by member -- so the block closes when the next
member's first row arrives.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path

from cobble.dataflow.fields.program_layout import ProgramLayout, layout_of
from cobble.dataflow.fields.side_tables import DeclaredCell, DeclaredRecord
from cobble.dataflow.fixpoint import rows
from cobble.dataflow.layout import Cell, Record


@dataclass(frozen=True)
class _Columns:
    """One row's arrays, each as long as ``extents`` and indexed by position."""

    names: tuple[str, ...]
    records: tuple[str, ...]
    paths: tuple[tuple[str, ...], ...]
    starts: tuple[int, ...]
    lengths: tuple[int, ...]
    levels: tuple[int, ...]
    pics: tuple[str, ...]
    usages: tuple[str, ...]
    redefines: tuple[str, ...]
    occurs: tuple[int, ...]
    values: tuple[str, ...]
    figurative: tuple[bool, ...]
    indexes: tuple[tuple[int, ...], ...]
    decls: tuple[int, ...]
    ordinals: tuple[int, ...]
    parents: tuple[int, ...]
    origins: tuple[str, ...]
    record_sizes: tuple[int, ...]
    record_positions: tuple[int, ...]


@dataclass(frozen=True)
class MemberLayout:
    """One member of a table, and the records its rows spell out."""

    member: str
    layout: ProgramLayout


def _columns(row: rows.Row) -> _Columns:
    return _Columns(
        names=rows.strings(row, "names"),
        records=rows.strings(row, "records"),
        paths=rows.string_lists(row, "paths"),
        starts=rows.numbers(row, "starts"),
        lengths=rows.numbers(row, "lengths"),
        levels=rows.numbers(row, "levels"),
        pics=rows.strings(row, "pics"),
        usages=rows.strings(row, "usages"),
        redefines=rows.strings(row, "redefines"),
        occurs=rows.numbers(row, "occurs"),
        values=rows.strings(row, "values"),
        figurative=rows.flags(row, "figurative"),
        indexes=rows.number_lists(row, "indexes"),
        decls=rows.numbers(row, "decls"),
        ordinals=rows.numbers(row, "ordinals"),
        parents=rows.numbers(row, "parents"),
        origins=rows.strings(row, "origins"),
        record_sizes=rows.numbers(row, "record_sizes"),
        record_positions=rows.numbers(row, "record_positions"),
    )


def _declared_cell(columns: _Columns, n: int) -> DeclaredCell:
    return DeclaredCell(
        cell=Cell(
            record=columns.records[n],
            name=columns.names[n],
            path=columns.paths[n],
            start=columns.starts[n],
            length=columns.lengths[n],
            level=columns.levels[n],
            pic=columns.pics[n],
            usage=columns.usages[n],
            redefines=columns.redefines[n],
            occurs=columns.occurs[n],
            value=columns.values[n],
            value_is_figurative=columns.figurative[n],
            index=columns.indexes[n],
            decl=columns.decls[n],
            ordinal=columns.ordinals[n],
            parent=columns.parents[n],
        ),
        record=DeclaredRecord(
            origin=columns.origins[n],
            size=columns.record_sizes[n],
            position=columns.record_positions[n],
        ),
    )


def _declared_cells(row: rows.Row) -> tuple[DeclaredCell, ...]:
    """Every cell one row published, in the order its columns hold them."""
    columns = _columns(row)
    return tuple(
        _declared_cell(columns, n) for n in range(len(columns.record_positions))
    )


def _ordered(cells: Sequence[DeclaredCell]) -> tuple[Cell, ...]:
    """One record's cells back in the order ``record_cells`` emitted them.

    Addressed rather than sorted: a record's ordinals run 0 to n-1 without gaps,
    because an ordinal *is* the position the cell was emitted at, and an 01
    REDEFINES folded into the record shifts its whole block up by the length of
    what came before it. Restoring that order is not cosmetic -- a cell's
    ``parent`` is an ordinal, and cells arrive here grouped by the name they were
    published under rather than by the record they sit in.
    """
    placed = {declared.cell.ordinal: declared.cell for declared in cells}
    return tuple(placed[n] for n in range(len(placed)))


def _record(cells: Sequence[DeclaredCell]) -> Record:
    """One record, named the way its cells name it.

    An 01 REDEFINES collapsed two names onto one piece of storage when the layout
    was built, so every cell here already carries the head of that cluster.
    """
    return Record(
        name=cells[0].cell.record,
        origin=cells[0].record.origin,
        size=cells[0].record.size,
        cells=_ordered(cells),
    )


def _at(cells: Sequence[DeclaredCell], position: int) -> tuple[DeclaredCell, ...]:
    return tuple(one for one in cells if one.record.position == position)


def _records(cells: Sequence[DeclaredCell]) -> tuple[Record, ...]:
    """One member's records in declaration order, which is what places them.

    Sections are laid end to end at bases accumulated in this order, so a record
    out of place would address its cells into another record's bytes.
    """
    positions = sorted({one.record.position for one in cells})
    return tuple(_record(_at(cells, position)) for position in positions)


def _member_of(row: rows.Row) -> str:
    return rows.text(row, "program").upper()


def _block_cells(block: Iterable[rows.Row]) -> tuple[DeclaredCell, ...]:
    return tuple(cell for row in block for cell in _declared_cells(row))


def declared_layouts(path: Path) -> Iterator[MemberLayout]:
    """Each member the table holds, in the order it holds them, one at a time.

    A generator and not a mapping: the caller is a corpus stage that analyses one
    member and moves on, so holding every member's records would make the peak the
    corpus's rather than the largest member's. One read of the file, so no member is
    parsed twice either.
    """
    return (
        MemberLayout(member=member, layout=layout_of(_records(_block_cells(block))))
        for member, block in groupby(rows.stream(path), _member_of)
    )
