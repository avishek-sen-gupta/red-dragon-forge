"""MemoResolve — one run's resolve, answered once per program, node and range."""

from collections.abc import Mapping
from functools import cache

from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.resolution import Resolution
from cobble.dataflow.combine.resolve import Resolve
from cobble.dataflow.fields.extent_text import ByteRange


class MemoResolve:
    def __init__(self, tables: Mapping[str, ProgramTables], inner: Resolve) -> None:
        self._tables = tables
        self._inner = inner
        self._resolved = cache(self._fresh)

    def __call__(self, tables: ProgramTables, node: str, at: ByteRange) -> Resolution:
        return self._resolved(tables.program, node, at)

    def _fresh(self, program: str, node: str, at: ByteRange) -> Resolution:
        return self._inner(self._tables[program], node, at)
