"""What the runner does with a program it has neither a utility nor source for."""

from __future__ import annotations

import logging
from typing import Protocol

from infrastructure.zos.abend.system_abend import SystemAbend
from jackal.model import ProgramRef, QualifiedStep
from jackal.results import Abended, Completed, ProgramResult

logger = logging.getLogger(__name__)

MODULE_NOT_FOUND = SystemAbend(0x806)


class MissingProgramStrategy(Protocol):
    def settle(self, qualified: QualifiedStep, pgm: ProgramRef) -> ProgramResult: ...


class AbendMissingProgram(MissingProgramStrategy):
    """Abends the step S806, as z/OS does when it cannot find the load module."""

    def settle(self, qualified: QualifiedStep, pgm: ProgramRef) -> ProgramResult:
        return Abended(MODULE_NOT_FOUND)


class StubMissingProgram(MissingProgramStrategy):
    """Completes the step with RC 0 in place of the program, and warns."""

    def settle(self, qualified: QualifiedStep, pgm: ProgramRef) -> ProgramResult:
        logger.warning(
            "%s: no program %s; stubbed with RC 0", qualified.rendered(), pgm.name
        )
        return Completed(0)
