"""Compiles a step's program as z/OS links a load module: the program, the programs it CALLs, and the coprocessors injected for it."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.project.coprocessor_compile import CoprocessorSpec, compile_program
from interpreter.project.types import LinkedProgram
from jackal.cobol_files import ProgramFile
from jackal.file_definitions import program_files_of
from jackal.le_abend import LE_STUBS
from jackal.model import ProgramRef
from jackal.program_sources import CobolSource


@dataclass(frozen=True)
class CompiledProgram:
    linked: LinkedProgram
    files: tuple[ProgramFile, ...]


@dataclass(frozen=True)
class ProgramCompiler:
    bridge_jar: str
    copybook_dirs: tuple[Path, ...]
    source_dirs: tuple[Path, ...]
    coprocessors: tuple[CoprocessorSpec, ...]
    linked: Mapping[ProgramRef, CobolSource] = field(default_factory=dict)

    def compiled(self, source: str) -> CompiledProgram:
        if not self.bridge_jar:
            raise ValueError(
                "PROLEAP_BRIDGE_JAR not set; required to run a COBOL program"
            )
        parser = ProLeapCobolParser(
            runner=RealSubprocessRunner(),
            bridge_jar=self.bridge_jar,
            copybook_dirs=list(self.copybook_dirs),
        )
        linked = compile_program(
            source.encode("utf-8"),
            parser,
            self.coprocessors,
            source_search_dirs=(*self.source_dirs, LE_STUBS),
            linked_subprogram_sources={
                pgm.name: linked.text.encode("utf-8")
                for pgm, linked in self.linked.items()
            },
        )
        return CompiledProgram(linked, program_files_of(linked))
