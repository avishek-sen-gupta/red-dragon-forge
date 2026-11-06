"""One program as the lowering reads it: its CFG, the fixpoint's statements, its layout and its VALUE clauses."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from cobble.dataflow.fields.extent import CellIndex, operand_extents
from cobble.dataflow.fields.image import initial_image
from cobble.dataflow.fields.program_layout import program_layout
from cobble.dataflow.fields.transfer import Statement
from cobble.dataflow.fields.values import ValueSet
from cobble.dataflow.fixpoint.fixpoint import program_statements
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.program import program_cfg
from cobol_asg.asg_types import CobolASG
from cobol_memory.field_extent import FieldExtent
from cobol_memory.region_id import RegionId


@dataclass(frozen=True)
class Program:
    """``file_statuses`` are the bytes of every FILE STATUS field, which any file
    statement may set; ``image`` is what each WORKING-STORAGE VALUE clause puts in
    its field before the first statement runs."""

    cfg: Cfg
    statements: Mapping[str, Statement]
    index: CellIndex
    file_statuses: tuple[FieldExtent, ...]
    image: Mapping[FieldExtent, ValueSet]

    def initial(self, region: RegionId, offset: int) -> int:
        """The byte the VALUE clauses put at ``offset``, or -1 when they do not
        agree on exactly one."""
        covering = tuple(
            (extent, values)
            for extent, values in self.image.items()
            if extent.region is region and extent.start <= offset < extent.end
        )
        found = frozenset(
            value[offset - extent.start]
            for extent, values in covering
            for value in values.values
            if len(value) == extent.length
        )
        whole = all(
            values.complete and len(values.values) == 1 for _, values in covering
        )
        return next(iter(found)) if whole and len(found) == 1 else -1


def program_of(asg: CobolASG) -> Program:
    cfg = program_cfg(asg)
    layout = program_layout(asg)
    index = layout.index
    return Program(
        cfg,
        program_statements(asg, cfg),
        index,
        tuple(
            extent
            for entry in asg.file_control
            if entry.file_status_var.name
            for extent in operand_extents(entry.file_status_var, index).extents
        ),
        initial_image(layout.records, index),
    )
