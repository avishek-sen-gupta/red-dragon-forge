"""Execution results: each step's outcome and the job's."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from jackal.model import QualifiedStep, UnexpandedCall


@dataclass(frozen=True)
class Completed:
    rc: int

    def rcs(self) -> tuple[int, ...]:
        return (self.rc,)

    def rendered(self) -> str:
        return f"RC={self.rc}"


class BypassReason(Enum):
    COND_SATISFIED = "COND_SATISFIED"
    ONLY_WITHOUT_ABEND = "ONLY_WITHOUT_ABEND"
    REFERENCED_STEP_NOT_RUN = "REFERENCED_STEP_NOT_RUN"


@dataclass(frozen=True)
class Bypassed:
    reason: BypassReason

    def rcs(self) -> tuple[int, ...]:
        return ()

    def rendered(self) -> str:
        return f"bypassed ({self.reason.value})"


@dataclass(frozen=True)
class AfterJobCond:
    step: QualifiedStep


@dataclass(frozen=True)
class Flushed:
    cause: AfterJobCond

    def rcs(self) -> tuple[int, ...]:
        return ()

    def rendered(self) -> str:
        return f"flushed (JOB COND met at {self.cause.step.rendered()})"


@dataclass(frozen=True)
class SkippedUnresolved:
    def rcs(self) -> tuple[int, ...]:
        return ()

    def rendered(self) -> str:
        return "skipped (unresolved reference)"


StepOutcome: TypeAlias = Completed | Bypassed | Flushed | SkippedUnresolved


@dataclass(frozen=True)
class StepResult:
    step: QualifiedStep | UnexpandedCall
    outcome: StepOutcome

    @property
    def name(self) -> str:
        return self.step.rendered()


@dataclass(frozen=True)
class JobCompleted:
    max_rc: int


@dataclass(frozen=True)
class JobResult:
    steps: tuple[StepResult, ...]

    @property
    def outcome(self) -> JobCompleted:
        return JobCompleted(
            max((rc for s in self.steps for rc in s.outcome.rcs()), default=0)
        )
