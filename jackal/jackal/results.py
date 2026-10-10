"""Execution results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from jackal.model import QualifiedStep, UnexpandedCall


class StepDisposition(Enum):
    EXECUTED = "EXECUTED"
    BYPASSED = "BYPASSED"


@dataclass(frozen=True)
class StepResult:
    step: QualifiedStep | UnexpandedCall
    return_code: int
    disposition: StepDisposition = StepDisposition.EXECUTED

    @property
    def name(self) -> str:
        return self.step.rendered()

    @property
    def ran(self) -> bool:
        return self.disposition is StepDisposition.EXECUTED


@dataclass(frozen=True)
class JobResult:
    steps: tuple[StepResult, ...]
