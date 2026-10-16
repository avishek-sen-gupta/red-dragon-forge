"""A live view of a region's program cache that hands each program out with the name it is entered by."""

from __future__ import annotations

from collections.abc import Iterator, Mapping

from cics.entered_program import EnteredProgram
from interpreter.project.types import LinkedProgram


class EnteredPrograms(Mapping[str, EnteredProgram]):
    def __init__(self, program_cache: Mapping[str, LinkedProgram]) -> None:
        self._program_cache = program_cache

    def __getitem__(self, name: str) -> EnteredProgram:
        return EnteredProgram(name, self._program_cache[name])

    def __iter__(self) -> Iterator[str]:
        return iter(self._program_cache)

    def __len__(self) -> int:
        return len(self._program_cache)
