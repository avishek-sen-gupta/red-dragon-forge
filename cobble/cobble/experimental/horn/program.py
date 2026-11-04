"""One program as the lowering reads it: its CFG, the fixpoint's statements, and its layout."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from cobble.dataflow.fields.extent import CellIndex, operand_extents
from cobble.dataflow.fields.program_layout import program_layout
from cobble.dataflow.fields.transfer import Statement
from cobble.dataflow.fixpoint.fixpoint import program_statements
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.program import program_cfg
from cobol_asg.asg_types import CobolASG
from cobol_memory.field_extent import FieldExtent


@dataclass(frozen=True)
class Program:
    """``file_statuses`` are the bytes of every FILE STATUS field, which any file
    statement may set."""

    cfg: Cfg
    statements: Mapping[str, Statement]
    index: CellIndex
    file_statuses: tuple[FieldExtent, ...]


def program_of(asg: CobolASG) -> Program:
    cfg = program_cfg(asg)
    index = program_layout(asg).index
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
    )
