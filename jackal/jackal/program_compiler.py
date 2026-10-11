"""Compiles a step's program as z/OS links a load module: the program, the programs it CALLs, and the coprocessors injected for it."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.cobol_statements import dialect_parsers_in_scope
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.project.coprocessor_compile import CoprocessorSpec, compile_program
from interpreter.project.types import LinkedProgram
from jackal.cobol_files import ProgramFile, program_files

_MAIN_MODULE = Path("__main__.cbl")


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
        _, linked = compile_program(
            source.encode("utf-8"),
            parser,
            self.coprocessors,
            source_search_dirs=self.source_dirs,
        )
        sources = (source.encode("utf-8"), *_callee_sources(linked))
        with dialect_parsers_in_scope([s.dialect_parser for s in self.coprocessors]):
            asgs = tuple(parser.parse(text) for text in sources)
        return CompiledProgram(
            linked, tuple(f for asg in asgs for f in program_files(asg))
        )


def _callee_sources(linked: LinkedProgram) -> Sequence[bytes]:
    return tuple(
        path.read_bytes()
        for path in linked.modules
        if path != _MAIN_MODULE and path.is_file()
    )
