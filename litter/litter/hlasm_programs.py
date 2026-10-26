"""The HLASM programs a build lowers, and the linker their presence calls for."""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from interpreter.project.types import LinkedProgram


class HlasmPrograms(Protocol):
    def lowered(self, work_dir: Path) -> dict[str, tuple[Path, ...]]: ...

    def linked(self, units: Sequence[Path], work_dir: Path) -> LinkedProgram: ...
