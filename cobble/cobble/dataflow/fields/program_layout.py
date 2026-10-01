"""One program's records and the index over them, carried together.

The two are built from the same walk and are useless apart: ``initial_image``
wants the records, every extent question wants the index, and an index built from
other records than the image was seeded from would place a VALUE in storage
nothing addresses. Passing the pair means a caller that already has it -- one
reading the declared extents out of ``extents.jsonl`` rather than laying the
DATA DIVISION out again -- hands over both halves or neither.
"""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fields.extent import CellIndex, cell_index
from cobble.dataflow.layout import Record, program_records
from cobol_asg.asg_types import CobolASG


@dataclass(frozen=True)
class ProgramLayout:
    """Every record one program declares, and the cells of all of them indexed."""

    records: tuple[Record, ...]
    index: CellIndex


def layout_of(records: tuple[Record, ...]) -> ProgramLayout:
    """The index built from these records, so there is one construction path.

    Whether the records came from an ASG or from the extents table, the index over
    them is ``cell_index``'s answer and nothing else: a serialised index would be a
    second way to build the same thing, free to disagree with the first.
    """
    return ProgramLayout(records=records, index=cell_index(records))


def program_layout(asg: CobolASG) -> ProgramLayout:
    """The layout of a program whose DATA DIVISION is being read for the first time."""
    return layout_of(program_records(asg))


NO_LAYOUT = layout_of(())
