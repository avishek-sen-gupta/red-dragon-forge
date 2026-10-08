"""MemoResolve — one run's resolve, each program's positions walked once however many starts reach them."""

from collections.abc import Callable, Mapping
from functools import cache, partial

from cobble.dataflow.combine.closures import Closures
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.resolution import Resolution, joined
from cobble.dataflow.combine.resolve import Step, Vertex
from cobble.dataflow.fields.extent_text import ByteRange


class MemoResolve:
    def __init__(
        self,
        tables: Mapping[str, ProgramTables],
        step: Callable[[ProgramTables, Vertex], Step],
    ) -> None:
        self._tables = tables
        self._step = step
        self._closures = cache(self._fresh)

    def __call__(self, tables: ProgramTables, node: str, at: ByteRange) -> Resolution:
        return self._closures(tables.program).of(
            (node, at), f"resolve {tables.program}"
        )

    def _fresh(self, program: str) -> Closures[Vertex, Resolution]:
        return Closures(
            partial(self._step, self._tables[program]), joined, Resolution()
        )
