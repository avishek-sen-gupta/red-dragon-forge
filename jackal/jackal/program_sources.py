"""Where the runner finds a program's COBOL source."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from jackal.model import ProgramRef


@dataclass(frozen=True)
class CobolSource:
    text: str


@dataclass(frozen=True)
class SourceNotFound:
    pass


class LinkedProgramNotFound(Exception):
    def __init__(self, program: ProgramRef):
        super().__init__(f"no COBOL source for linked program {program.name}")
        self.program = program


class ProgramSources(Protocol):
    def find(self, pgm: ProgramRef) -> CobolSource | SourceNotFound: ...


@dataclass(frozen=True)
class DirectoryProgramSources(ProgramSources):
    directory: Path

    def find(self, pgm: ProgramRef) -> CobolSource | SourceNotFound:
        path = self.directory / f"{pgm.name}.cbl"
        return CobolSource(path.read_text()) if path.is_file() else SourceNotFound()
