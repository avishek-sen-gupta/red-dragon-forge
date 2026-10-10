"""Parsed and expanded model values for runtime tests, built from short descriptions."""

from collections.abc import Sequence

from jackal.allocation import DdEnvironment, allocate
from jackal.catalog import DatasetCatalog
from jackal.jcl.wire import disp_from_words
from jackal.model import (
    DD,
    DSN,
    AbendMode,
    AllPriorSteps,
    BypassTest,
    CondOp,
    DdName,
    DirectDSN,
    Disp,
    Job,
    JobStatement,
    OwnScope,
    ProgramRef,
    ProgramStep,
    QualifiedStep,
    RcComparison,
    StepCondition,
    StepName,
    StepRef,
    StepReference,
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


def allocated(
    step: ProgramStep[StepReference], catalog: DatasetCatalog
) -> DdEnvironment:
    return allocate(QualifiedStep((), step), step, catalog)
