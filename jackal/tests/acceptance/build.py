"""Short constructors for expected model values in the acceptance suite."""

from jackal.model import (
    DD,
    AbendMode,
    AllPriorSteps,
    BackwardRef,
    BypassTest,
    CalledProcScope,
    ConcatMember,
    CondOp,
    DdName,
    DirectDSN,
    Disp,
    DispAbnormal,
    DispNormal,
    DispStatus,
    DummyDSN,
    InStreamDSN,
    NoDSN,
    NotCoded,
    Omitted,
    OwnScope,
    ProcCall,
    ProcRef,
    ProgramRef,
    ProgramStep,
    QualifiedStep,
    RcComparison,
    ResolvedDd,
    ResolvedProc,
    ResolvedProcCall,
    StepCondition,
    StepName,
    StepRef,
    TempRef,
    UnexpandedCall,
    Unnamed,
    UnresolvedDd,
)
from jackal.value_parts import Symbol, SymbolName, literal
from tests.acceptance.conftest import FIXTURES

NO_COND = StepCondition((), AbendMode.NORMAL)


def name(text: str) -> StepName:
    return StepName(text)


def proc(text: str) -> ProcRef:
    return ProcRef(text)


def dd_name(text: str) -> DdName:
    return DdName(text)


def ref(step: str) -> StepRef:
    return StepRef(OwnScope(), StepName(step))


def ref_in(call: str, step: str) -> StepRef:
    return StepRef(CalledProcScope(StepName(call)), StepName(step))


def disp(status: str, normal: str = "", abnormal: str = "") -> Disp:
    return Disp(
        DispStatus[status],
        DispNormal[normal] if normal else Omitted(),
        DispAbnormal[abnormal] if abnormal else Omitted(),
    )


SHR = disp("SHR")
OLD = disp("OLD")
DEFAULT_DISP = disp("NEW")


def dataset(ddname: str, dsn: str, d: Disp | NotCoded = SHR) -> DD:
    return DD(DdName(ddname), DirectDSN(literal(dsn)), d)


def temp(ddname: str, temp_name: str, d: Disp) -> DD:
    return DD(DdName(ddname), TempRef(temp_name), d)


def in_stream(ddname: str, lines: tuple[str, ...]) -> DD:
    return DD(DdName(ddname), InStreamDSN(), NotCoded(), in_stream=lines)


def dummy(ddname: str) -> DD:
    return DD(DdName(ddname), DummyDSN(), NotCoded())


def sysout(ddname: str) -> DD:
    return DD(DdName(ddname), NoDSN(), NotCoded(), sysout=True)


def backref(ddname: str, step: StepRef, target_dd: str, d: Disp = SHR) -> DD:
    return DD(DdName(ddname), BackwardRef(step, UnresolvedDd(DdName(target_dd))), d)


def resolved_backref(
    ddname: str, step: QualifiedStep, target_dd: str, d: Disp = SHR
) -> DD:
    found = next(dd for dd in step.step.dds if dd.ddname == DdName(target_dd))
    return DD(DdName(ddname), BackwardRef(step.reference(), ResolvedDd(found)), d)


def concat(ddname: str, first: str, rest: tuple[ConcatMember, ...]) -> DD:
    return DD(DdName(ddname), DirectDSN(literal(first)), SHR, concatenated=rest)


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
        ProgramRef(program),
        dds,
        condition,
        literal(parm) if parm else (),
    )


def symbol(sym: str) -> Symbol:
    return Symbol(SymbolName(sym))


def qualified(
    coordinates: tuple[ResolvedProcCall, ...], step: ProgramStep
) -> QualifiedStep:
    return QualifiedStep(coordinates, step)


def called(call: ProcCall, prc: str) -> ResolvedProcCall:
    from jackal.jcl.parser import parse_proc

    return ResolvedProcCall(
        call, ResolvedProc(parse_proc((FIXTURES / prc).read_text()))
    )


def unexpanded(coordinates: tuple[ResolvedProcCall, ...]) -> UnexpandedCall:
    return UnexpandedCall(coordinates)
