"""A program the region enters: its name, and the linked image that holds it."""

from __future__ import annotations

from dataclasses import dataclass

from interpreter.project.program_entry import ProgramEntry
from interpreter.project.types import LinkedProgram


@dataclass(frozen=True)
class EnteredProgram:
    name: str
    image: LinkedProgram

    def entry(self) -> ProgramEntry:
        return ProgramEntry(self.name)
