"""Execution results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StepDisposition(Enum):
    EXECUTED = "EXECUTED"
    BYPASSED = "BYPASSED"


@dataclass(frozen=True)
class StepResult:
    name: str
    return_code: int
    ran: bool
    disposition: StepDisposition = StepDisposition.EXECUTED


@dataclass(frozen=True)
class JobResult:
    steps: tuple[StepResult, ...]
