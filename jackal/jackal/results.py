"""Execution results: each step's outcome and the job's."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from infrastructure.zos.abend.system_abend import SystemAbend
from infrastructure.zos.abend.user_abend import UserAbend
from jackal.model import DdName, QualifiedStep, UnexpandedCall


@dataclass(frozen=True)
class Completed:
    rc: int

    def rcs(self) -> tuple[int, ...]:
        return (self.rc,)

    def rendered(self) -> str:
        return f"RC={self.rc}"


@dataclass(frozen=True)
class Abended:
    code: SystemAbend | UserAbend

    def rcs(self) -> tuple[int, ...]:
        return ()

    def rendered(self) -> str:
        return f"abended {self.code.rendered()}"


ProgramResult: TypeAlias = Completed | Abended


class BypassReason(Enum):
    COND_SATISFIED = "COND_SATISFIED"
    ONLY_WITHOUT_ABEND = "ONLY_WITHOUT_ABEND"
    IF_CONDITION_FALSE = "IF_CONDITION_FALSE"


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

    def rendered(self) -> str:
        return f"JOB COND met at {self.step.rendered()}"


@dataclass(frozen=True)
class AfterAbend:
    step: QualifiedStep

    def rendered(self) -> str:
        return f"abended at {self.step.rendered()}"


@dataclass(frozen=True)
class AfterAllocationFailure:
    step: QualifiedStep

    def rendered(self) -> str:
        return f"allocation failed at {self.step.rendered()}"


FlushCause: TypeAlias = AfterJobCond | AfterAbend | AfterAllocationFailure


@dataclass(frozen=True)
class Flushed:
    cause: FlushCause

    def rcs(self) -> tuple[int, ...]:
        return ()

    def rendered(self) -> str:
        return f"flushed ({self.cause.rendered()})"


@dataclass(frozen=True)
class SkippedUnresolved:
    def rcs(self) -> tuple[int, ...]:
        return ()

    def rendered(self) -> str:
        return "skipped (unresolved reference)"


class AllocationError(Enum):
    DATASET_NOT_FOUND = "DATASET_NOT_FOUND"
    DUPLICATE_NAME = "DUPLICATE_NAME"
    TEMP_NOT_CREATED = "TEMP_NOT_CREATED"
    GDG_BASE_NOT_FOUND = "GDG_BASE_NOT_FOUND"


@dataclass(frozen=True)
class AllocationFailed:
    ddname: DdName
    error: AllocationError

    def rcs(self) -> tuple[int, ...]:
        return ()

    def rendered(self) -> str:
        return f"allocation failed (DD {self.ddname.text}: {self.error.value})"


StepOutcome: TypeAlias = (
    Completed | Abended | Bypassed | Flushed | SkippedUnresolved | AllocationFailed
)


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

    def succeeded(self) -> bool:
        return self.max_rc == 0


@dataclass(frozen=True)
class JobAllocationFailed:
    step: QualifiedStep | UnexpandedCall
    failure: AllocationFailed

    def succeeded(self) -> bool:
        return False


@dataclass(frozen=True)
class JobAbended:
    step: QualifiedStep | UnexpandedCall
    code: SystemAbend | UserAbend

    def succeeded(self) -> bool:
        return False


JobOutcome: TypeAlias = JobCompleted | JobAbended | JobAllocationFailed


def _failure(result: StepResult) -> tuple[JobAbended | JobAllocationFailed, ...]:
    match result.outcome:
        case AllocationFailed():
            return (JobAllocationFailed(result.step, result.outcome),)
        case Abended():
            return (JobAbended(result.step, result.outcome.code),)
        case _:
            return ()


@dataclass(frozen=True)
class JobResult:
    steps: tuple[StepResult, ...]

    @property
    def outcome(self) -> JobOutcome:
        completed = JobCompleted(
            max((rc for s in self.steps for rc in s.outcome.rcs()), default=0)
        )
        failures = (f for s in self.steps for f in _failure(s))
        return next(failures, completed)
