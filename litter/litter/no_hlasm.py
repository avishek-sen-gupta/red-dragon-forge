"""No HLASM programs: nothing to lower, and the image linked as COBOL alone."""

from collections.abc import Sequence
from pathlib import Path

from interpreter.project.cobol_compile import link_units
from interpreter.project.types import LinkedProgram
from litter.hlasm_programs import HlasmPrograms


class NoHlasm(HlasmPrograms):
    def lowered(self, work_dir: Path) -> dict[str, tuple[Path, ...]]:
        return {}

    def linked(self, units: Sequence[Path], work_dir: Path) -> LinkedProgram:
        return link_units(units, work_dir)


NO_HLASM = NoHlasm()
