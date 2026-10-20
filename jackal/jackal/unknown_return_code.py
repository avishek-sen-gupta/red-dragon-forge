"""What the runner does with a step whose RETURN-CODE is unknown, as after a tolerated CALL to a program outside the run unit."""

from __future__ import annotations

import logging
from typing import Protocol

from interpreter.cobol.symbolic_return_code_error import SymbolicReturnCodeError
from jackal.model import QualifiedStep
from jackal.results import Completed, ProgramResult

logger = logging.getLogger(__name__)


class UnknownReturnCodeStrategy(Protocol):
    def settle(
        self, qualified: QualifiedStep, unknown: SymbolicReturnCodeError
    ) -> ProgramResult: ...


class RaiseUnknownReturnCode(UnknownReturnCodeStrategy):
    """Stops the job: no return code is the step's result, so none is invented."""

    def settle(
        self, qualified: QualifiedStep, unknown: SymbolicReturnCodeError
    ) -> ProgramResult:
        raise unknown


class ZeroUnknownReturnCode(UnknownReturnCodeStrategy):
    """Completes the step with RC 0, and warns."""

    def settle(
        self, qualified: QualifiedStep, unknown: SymbolicReturnCodeError
    ) -> ProgramResult:
        logger.warning(
            "%s: RETURN-CODE is unknown after the step; completed with RC 0",
            qualified.rendered(),
        )
        return Completed(0)
