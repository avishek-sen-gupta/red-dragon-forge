"""TableCalleeAreas — callee areas from the analysed programs' tables, the parse cache only for the rest."""

from collections.abc import Mapping
from functools import cache

from cobble.dataflow.combine.callee_areas import CalleeAreas
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.fields.extent_text import NO_RANGE, ByteRange
from cobble.dataflow.jumps.jump_kind import JumpKind


class TableCalleeAreas(CalleeAreas):
    def __init__(
        self, tables: Mapping[str, ProgramTables], outside: CalleeAreas
    ) -> None:
        self._tables = tables
        self._outside = cache(outside.area)

    def area(self, callee: str, kind: JumpKind, param: int) -> ByteRange:
        if callee not in self._tables:
            return self._outside(callee, kind, param)
        return dict(self._tables[callee].received).get(param, NO_RANGE)
