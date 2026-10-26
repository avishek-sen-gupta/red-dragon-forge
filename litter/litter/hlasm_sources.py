"""HLASM programs present: each source lowered with the bridge parser, and the image linked with COBOL-HLASM binding."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from hlasm_asg.hlasm_ast_parser import HlasmAstParser
from interpreter.project.hlasm_compile import link_hlasm_units, lower_hlasm_program
from interpreter.project.source_file import SourceFile
from interpreter.project.types import LinkedProgram
from litter.hlasm_programs import HlasmPrograms


@dataclass(frozen=True)
class HlasmSources(HlasmPrograms):
    sources: Mapping[str, Path]
    parser: HlasmAstParser

    def lowered(self, work_dir: Path) -> dict[str, tuple[Path, ...]]:
        return {
            program: lower_hlasm_program(
                SourceFile(source, source.read_bytes()),
                parser=self.parser,
                work_dir=work_dir,
            )
            for program, source in self.sources.items()
        }

    def linked(self, units: Sequence[Path], work_dir: Path) -> LinkedProgram:
        return link_hlasm_units(units, work_dir)
