"""One program as the lowering reads it: CFG, statements, 88-levels and declared extents."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cobble.dataflow.fields.extent_line import ExtentLine
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.conditions import EightyEight, condition_index
from cobble.dataflow.srccfg.program import program_cfg
from cobble.dataflow.srccfg.statements import statement_index
from cobol_asg.asg_types import CobolASG
from cobol_asg.cobol_statements import CobolStatementType


@dataclass(frozen=True)
class Program:
    cfg: Cfg
    statements: Mapping[str, CobolStatementType]
    conditions: Mapping[str, EightyEight]
    extents: tuple[ExtentLine, ...]


def program_of(asg: CobolASG, extents: Sequence[ExtentLine]) -> Program:
    cfg = program_cfg(asg)
    return Program(
        cfg,
        statement_index(asg),
        condition_index(asg),
        tuple(row for row in extents if row.program == cfg.program),
    )
