"""Parsed and expanded model values for runtime tests, built from short descriptions."""

from collections.abc import Sequence

from jackal.dsn import DSN, DdName, DirectDSN
from jackal.jcl.wire import disp_from_words
from jackal.model import (
    DD,
    AbendMode,
    AllPriorSteps,
    BypassTest,
    CondOp,
    Disp,
    Job,
    JobStatement,
    ProgramRef,
    ProgramStep,
    QualifiedStep,
    RcComparison,
    StepCondition,
    StepName,
    StepRef,
    OwnScope,
)
from jackal.value_parts import literal


def disp(*words: str) -> Disp:
    return disp_from_words(words)


def dd(ddname: str, dsn: DSN[StepRef] | str, d: Disp = disp("SHR")) -> DD[StepRef]:
    return DD(
        DdName(ddname), DirectDSN(literal(dsn)) if isinstance(dsn, str) else dsn, d
    )


def ref(step: str) -> StepRef:
    return StepRef(OwnScope(), StepName(step))


def cond(
    *tests: tuple[int, str, str], mode: AbendMode = AbendMode.NORMAL
) -> StepCondition[StepRef]:
    return StepCondition(
        tuple(
            BypassTest(
                RcComparison(code, CondOp[op]),
                ref(step) if step else AllPriorSteps(),
            )
            for code, op, step in tests
        ),
        mode,
    )


def program(
    label: str,
    pgm: str,
    dds: Sequence[DD[StepRef]] = (),
    condition: StepCondition[StepRef] = StepCondition((), AbendMode.NORMAL),
    parm: str = "",
) -> ProgramStep[StepRef]:
    return ProgramStep(
        StepName(label),
        ProgramRef(pgm),
        tuple(dds),
        condition,
        literal(parm) if parm else (),
    )


def job(
    name: str,
    steps: Sequence[JobStatement],
    end_job_tests: Sequence[tuple[int, str]] = (),
) -> Job:
    return Job(
        name,
        tuple(steps),
        tuple(RcComparison(code, CondOp[op]) for code, op in end_job_tests),
    )


def ran(label: str, pgm: str = "PGM") -> QualifiedStep:
    return QualifiedStep((), ProgramStep(StepName(label), ProgramRef(pgm)))
