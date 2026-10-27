"""The extents table as an input: what a reader gets back, and what still reads it.

Two claims, and they pull against each other. The table has to carry enough for a
reader to rebuild ``layout``'s answer exactly -- not approximately, not the
geometry alone -- and it has to stay the file the published consumers already
read, with the four fields they ask for unmoved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.emit import _declared_extents
from cobble.dataflow.fields.extents_input import declared_layouts
from cobble.dataflow.fields.program_layout import ProgramLayout, program_layout
from cobble.dataflow.fields.side_tables import extent_row
from cobble.dataflow.fields.stale_extents import StaleExtents
from cobble.dataflow.fixpoint.query import Side, store_of
from cobble.dataflow.layout import Cell
from cobol_asg.asg_types import CobolASG
from cobble.parsing.asg_cache import first_program_at

CACHE = Path(__file__).resolve().parents[3] / "out-parsed"

MEMBER = "COMEN01C"
MENU_RECORD = "CARDDEMO-MAIN-MENU-OPTIONS"

PGMNAME = Cell(
    record=MENU_RECORD,
    name="CDEMO-MENU-OPT-PGMNAME",
    path=(
        MENU_RECORD,
        "CDEMO-MENU-OPTIONS",
        "CDEMO-MENU-OPT",
        "CDEMO-MENU-OPT-PGMNAME",
    ),
    start=39,
    length=8,
    level=15,
    pic="X(08)",
    usage="DISPLAY",
    redefines="",
    occurs=0,
    value="",
    value_is_figurative=False,
    index=(1,),
    decl=51,
    ordinal=51,
    parent=48,
)

FILLER = Cell(
    record=MENU_RECORD,
    name="FILLER_3",
    path=(MENU_RECORD, "CDEMO-MENU-OPTIONS-DATA", "FILLER_3"),
    start=39,
    length=8,
    level=10,
    pic="X(08)",
    usage="DISPLAY",
    redefines="",
    occurs=0,
    value="COACTVWC",
    value_is_figurative=False,
    index=(),
    decl=5,
    ordinal=5,
    parent=2,
)


def _written(layout: ProgramLayout, program: str, path: Path) -> Path:
    rows = tuple(extent_row(field) for field in _declared_extents(layout, program))
    path.write_text("".join(f"{row}\n" for _, row in rows), encoding="utf-8")
    return path


def _asg(member: str) -> CobolASG:
    path = CACHE / f"{member}.json"
    if not path.is_file():
        pytest.skip(f"no parsed cache for {member}; run cobble-parse-corpus")
    with cached_asg_dialect_parsers_registered():
        return first_program_at(path)


def _cell_at(layout: ProgramLayout, name: str) -> Cell:
    (found,) = [
        cell
        for record in layout.records
        if record.name == MENU_RECORD
        for cell in record.cells
        if cell.name == name and (cell.start, cell.length) == (39, 8)
    ]
    return found


def test_the_rows_rebuild_the_records_they_were_written_from(tmp_path: Path):
    """Every record field for field, not the extents a consumer could intersect.

    Read on the member whose menu table puts REDEFINES, OCCURS and VALUE over one
    piece of storage: ``CDEMO-MENU-OPT-PGMNAME(1)`` and ``FILLER_3`` are both the
    record's bytes 39 to 47, one reached through the table view and one through the
    literals that initialise it. Both are asserted whole, because the fields that
    distinguish them -- the path, the subscript, the declaration number, the
    ordinal, the parent, and the VALUE only one of them carries -- are exactly what
    a table carrying ranges alone would lose.
    """
    layout = program_layout(_asg(MEMBER))
    path = _written(layout, MEMBER, tmp_path / "extents.jsonl")

    (published,) = tuple(declared_layouts(path))

    assert (published.member, published.layout.records) == (MEMBER, layout.records)
    rebuilt = published.layout
    assert _cell_at(rebuilt, "CDEMO-MENU-OPT-PGMNAME") == PGMNAME
    assert _cell_at(rebuilt, "FILLER_3") == FILLER
    (menu,) = [record for record in rebuilt.records if record.name == MENU_RECORD]
    assert (menu.origin, menu.size, len(menu.cells)) == ("WORKING-STORAGE", 554, 108)


def test_rows_written_before_the_justified_column_are_refused_not_read_as_left_aligned(
    tmp_path: Path,
):
    path = _written(program_layout(_asg(MEMBER)), MEMBER, tmp_path / "extents.jsonl")
    older = [
        {
            column: cells
            for column, cells in json.loads(line).items()
            if column != "justified"
        }
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    path.write_text("".join(f"{json.dumps(row)}\n" for row in older), encoding="utf-8")

    with pytest.raises(StaleExtents, match="rerun cobble-extents"):
        tuple(declared_layouts(path))


def test_a_row_still_answers_the_four_fields_the_published_consumers_read(
    program_of, field, layout_of
):
    """The columns are additive: the old four come first and mean what they meant.

    Asserted through ``store_of``, which is the reader ``cobble-dataflow-fixpoint-query``
    and the trace query go through, rather than against the dict -- a row that
    parses but no longer answers ``ranges`` would pass the weaker check.
    """
    asg = program_of(
        [],
        data_fields=[
            field(
                1,
                "REC",
                children=[
                    field(5, "WS-A", "X(4)", offset=0),
                    field(5, "WS-B", "X(4)", offset=4),
                ],
            )
        ],
    )
    rows = [
        json.loads(row)
        for _, row in (
            extent_row(one) for one in _declared_extents(layout_of(asg), "PROGA")
        )
    ]

    declared = {row["id"]: row for row in rows}
    assert list(declared["PROGA.WS-B"])[:4] == ["id", "level", "usage", "extents"]
    assert (
        declared["PROGA.WS-B"]["level"],
        declared["PROGA.WS-B"]["usage"],
        declared["PROGA.WS-B"]["extents"],
    ) == (5, "DISPLAY", ["WS-B@working_storage[4:8]"])

    store = store_of(rows, (), ())
    (found,) = store.field("PROGA.WS-B")
    assert [(one.start, one.end) for one in found.ranges] == [(4, 8)]
    assert store.touching(found.ranges, Side.TARGET) == ()
