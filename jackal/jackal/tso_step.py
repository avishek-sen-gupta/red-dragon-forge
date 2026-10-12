"""A TSO monitor step: the DSN session its SYSTSIN runs, one RUN PROGRAM after another (TSO/E, Db2)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import reduce

from jackal.model import DD, ProgramRef, ProgramStep, StepReference, SystemAbend
from jackal.results import Abended, Completed, ProgramResult
from jackal.tso import TSO_COMMAND_DD, TsoRun, is_tso_monitor, tso_runs

_ABEND_RC = 12
_MONITOR_ABEND = SystemAbend(0x04C)
_RETURNS_ON_ABEND = "IKJEFT01"

RunProgram = Callable[[ProgramRef], ProgramResult]


def _commands(dds: Sequence[DD[StepReference]]) -> tuple[str, ...]:
    return tuple(
        line for dd in dds if dd.ddname.text == TSO_COMMAND_DD for line in dd.in_stream
    )


def dsn_runs(step: ProgramStep[StepReference]) -> tuple[TsoRun, ...]:
    if not is_tso_monitor(step.pgm.name):
        return ()
    return tso_runs(_commands(step.dds))


def _next(run_program: RunProgram, so_far: ProgramResult, run: TsoRun) -> ProgramResult:
    match so_far:
        case Abended():
            return so_far
        case Completed(rc=rc):
            return _highest(rc, run_program(ProgramRef(run.program)))


def _highest(rc: int, result: ProgramResult) -> ProgramResult:
    match result:
        case Abended():
            return result
        case Completed():
            return Completed(max(rc, result.rc))


def _monitored(monitor: str, session: ProgramResult) -> ProgramResult:
    match session:
        case Abended():
            return _abended(monitor)
        case Completed():
            return session


def _abended(monitor: str) -> ProgramResult:
    if monitor == _RETURNS_ON_ABEND:
        return Completed(_ABEND_RC)
    return Abended(_MONITOR_ABEND)


def run_tso_step(
    step: ProgramStep[StepReference], runs: Sequence[TsoRun], run_program: RunProgram
) -> ProgramResult:
    session = reduce(
        lambda so_far, run: _next(run_program, so_far, run), runs, Completed(0)
    )
    return _monitored(step.pgm.name.upper(), session)
