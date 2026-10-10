"""Short constructors for expected model values in the acceptance suite."""

from jackal.dsn import (
    BackwardRef,
    DirectDSN,
    DummyDSN,
    InStreamDSN,
    NoDSN,
    TempRef,
)
from jackal.model import (
    DD,
    AbendMode,
    AllPriorSteps,
    BypassTest,
    CalledProcScope,
    ConcatMember,
    CondOp,
    Disp,
    DispAbnormal,
    DispNormal,
    DispStatus,
    OwnScope,
    ProgramStep,
    RcComparison,
    StepCondition,
    StepName,
    StepRef,
    Unnamed,
)
from jackal.value_parts import Symbol, SymbolName, literal

NO_COND = StepCondition((), AbendMode.NORMAL)


def name(text: str) -> StepName:
    return StepName(text)


def ref(step: str) -> StepRef:
    return StepRef(OwnScope(), StepName(step))


def ref_in(call: str, step: str) -> StepRef:
    return StepRef(CalledProcScope(StepName(call)), StepName(step))


def disp(status: str, normal: str, abnormal: str) -> Disp:
    return Disp(DispStatus[status], DispNormal[normal], DispAbnormal[abnormal])


SHR = disp("SHR", "KEEP", "KEEP")
OLD = disp("OLD", "KEEP", "KEEP")
DEFAULT_DISP = disp("NEW", "DELETE", "DELETE")


def dataset(ddname: str, dsn: str, d: Disp = SHR) -> DD:
    return DD(ddname, DirectDSN(literal(dsn)), d)


def temp(ddname: str, temp_name: str, d: Disp) -> DD:
    return DD(ddname, TempRef(temp_name), d)


def in_stream(ddname: str, lines: tuple[str, ...]) -> DD:
    return DD(ddname, InStreamDSN(), DEFAULT_DISP, in_stream=lines)


def dummy(ddname: str) -> DD:
    return DD(ddname, DummyDSN(), DEFAULT_DISP)


def sysout(ddname: str) -> DD:
    return DD(ddname, NoDSN(), DEFAULT_DISP, sysout=True)


def backref(ddname: str, step: object, target_dd: str, d: Disp = SHR) -> DD:
    return DD(ddname, BackwardRef(step, target_dd), d)


def concat(ddname: str, first: str, rest: tuple[ConcatMember, ...]) -> DD:
    return DD(ddname, DirectDSN(literal(first)), SHR, concatenated=rest)


def member(dsn: str) -> ConcatMember:
    return ConcatMember(DirectDSN(literal(dsn)), SHR)


def on_step(code: int, op: str, target: object) -> BypassTest:
    return BypassTest(RcComparison(code, CondOp[op]), target)


def all_prior(code: int, op: str) -> BypassTest:
    return BypassTest(RcComparison(code, CondOp[op]), AllPriorSteps())


def cond(*tests: BypassTest, mode: str = "NORMAL") -> StepCondition:
    return StepCondition(tests, AbendMode[mode])


def pgm(
    label: str,
    program: str,
    dds: tuple[DD, ...] = (),
    condition: StepCondition = NO_COND,
    parm: str = "",
) -> ProgramStep:
    return ProgramStep(
        StepName(label) if label else Unnamed(),
        program,
        dds,
        condition,
        literal(parm) if parm else (),
    )


def symbol(sym: str) -> Symbol:
    return Symbol(SymbolName(sym))


def qualified(calls: tuple[object, ...], step: object) -> object:
    from jackal.expansion import QualifiedStep

    return QualifiedStep(calls, step)
