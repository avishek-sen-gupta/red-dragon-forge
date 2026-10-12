"""The JCL job model: what a job says, parsed, and each step and reference once PROC calls are expanded."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeAlias, TypeVar

from jackal.value_parts import SymbolName, Value, resolve

R = TypeVar("R", bound="StepRef | StepReference")
S = TypeVar("S", bound="StepRef | StepReference")


@dataclass(frozen=True)
class StepName:
    text: str

    def rendered(self) -> str:
        return self.text


@dataclass(frozen=True)
class Unnamed:
    def rendered(self) -> str:
        return ""


StepLabel: TypeAlias = StepName | Unnamed


@dataclass(frozen=True)
class ProgramRef:
    name: str


@dataclass(frozen=True)
class ProcRef:
    name: str


@dataclass(frozen=True)
class DdName:
    text: str


@dataclass(frozen=True)
class OwnScope:
    pass


@dataclass(frozen=True)
class CalledProcScope:
    call: StepName


RefScope: TypeAlias = OwnScope | CalledProcScope


@dataclass(frozen=True)
class StepRef:
    scope: RefScope
    step: StepName


@dataclass(frozen=True)
class ResolvedProc:
    proc: ProcDef


@dataclass(frozen=True)
class UnresolvedProc:
    proc: ProcRef


ProcCoordinate: TypeAlias = ResolvedProc | UnresolvedProc


@dataclass(frozen=True)
class ResolvedProcCall:
    call: ProcCall
    proc: ProcCoordinate

    def rendered(self) -> str:
        return self.call.label.rendered()


@dataclass(frozen=True)
class UnresolvedProcCall:
    name: StepName

    def rendered(self) -> str:
        return self.name.text


ProcCallCoordinate: TypeAlias = ResolvedProcCall | UnresolvedProcCall


@dataclass(frozen=True)
class ResolvedProgramStep:
    step: ProgramStep[StepReference]

    def rendered(self) -> str:
        return self.step.label.rendered()


@dataclass(frozen=True)
class UnresolvedProgramStep:
    name: StepName

    def rendered(self) -> str:
        return self.name.text


ProgramStepCoordinate: TypeAlias = ResolvedProgramStep | UnresolvedProgramStep


@dataclass(frozen=True)
class ResolvedDd:
    dd: DD[StepReference]

    def ddname(self) -> DdName:
        return self.dd.ddname

    def rendered(self) -> str:
        return self.dd.ddname.text


@dataclass(frozen=True)
class UnresolvedDd:
    name: DdName

    def ddname(self) -> DdName:
        return self.name

    def rendered(self) -> str:
        return self.name.text


DdCoordinate: TypeAlias = ResolvedDd | UnresolvedDd


@dataclass(frozen=True)
class StepReference:
    path: tuple[ProcCallCoordinate, ...]
    target: ProgramStepCoordinate

    def rendered(self) -> str:
        return ".".join((*(c.rendered() for c in self.path), self.target.rendered()))


@dataclass(frozen=True)
class Substitution(Generic[R]):
    """Symbol substitution in a DSN: the value substituted, and the kind of DSN a whole substituted name makes."""

    value: Callable[[Value], Value]
    dataset: Callable[[Value], DSN[R]]


@dataclass(frozen=True)
class DirectDSN:
    name: Value

    def dataset_name(self) -> str:
        return resolve(self.name)

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> DSN[S]:
        return self

    def substituted(self, substitution: Substitution[R]) -> DSN[R]:
        return substitution.dataset(substitution.value(self.name))


@dataclass(frozen=True)
class GenerationDSN:
    """A generation of a GDG relative to the current one: (+1) the next, (0) the current, (-1) the one before."""

    base: Value
    relative: int

    def base_name(self) -> str:
        return resolve(self.base)

    def dataset_name(self) -> str:
        sign = "+" if self.relative > 0 else ""
        return f"{self.base_name()}({sign}{self.relative})"

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> DSN[S]:
        return self

    def substituted(self, substitution: Substitution[R]) -> DSN[R]:
        return GenerationDSN(substitution.value(self.base), self.relative)


@dataclass(frozen=True)
class TempRef:
    name: str

    def dataset_name(self) -> str:
        raise TypeError(f"temporary dataset &&{self.name} is allocated by the catalog")

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> DSN[S]:
        return self

    def substituted(self, substitution: Substitution[R]) -> DSN[R]:
        return self


@dataclass(frozen=True)
class BackwardRef(Generic[R]):
    step: R
    dd: DdCoordinate

    def dataset_name(self) -> str:
        raise TypeError(f"referback to {self.dd.rendered()} is resolved by the runner")

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> DSN[S]:
        return backref(self)

    def substituted(self, substitution: Substitution[R]) -> DSN[R]:
        return self


@dataclass(frozen=True)
class StepDd:
    """*.ddname: an earlier DD of the same step, resolved by the runner against that step's DDs."""

    ddname: DdName

    def dataset_name(self) -> str:
        raise TypeError(f"referback to *.{self.ddname.text} is resolved by the runner")

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> StepDd:
        return self

    def substituted(self, substitution: Substitution[R]) -> StepDd:
        return self


@dataclass(frozen=True)
class InStreamDSN:
    def dataset_name(self) -> str:
        raise TypeError("in-stream data has no dataset")

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> DSN[S]:
        return self

    def substituted(self, substitution: Substitution[R]) -> DSN[R]:
        return self


@dataclass(frozen=True)
class DummyDSN:
    def dataset_name(self) -> str:
        raise TypeError("DUMMY has no dataset")

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> DSN[S]:
        return self

    def substituted(self, substitution: Substitution[R]) -> DSN[R]:
        return self


@dataclass(frozen=True)
class NoDSN:
    def dataset_name(self) -> str:
        raise TypeError("a DD with no DSN has no dataset")

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> DSN[S]:
        return self

    def substituted(self, substitution: Substitution[R]) -> DSN[R]:
        return self


@dataclass(frozen=True)
class NullifiedDSN:
    def dataset_name(self) -> str:
        raise TypeError("a nullified DSN names no dataset")

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> DSN[S]:
        return self

    def substituted(self, substitution: Substitution[R]) -> DSN[R]:
        return self


DSN: TypeAlias = (
    DirectDSN
    | GenerationDSN
    | TempRef
    | BackwardRef[R]
    | StepDd
    | InStreamDSN
    | DummyDSN
    | NoDSN
    | NullifiedDSN
)


class CondOp(Enum):
    GT = "GT"
    GE = "GE"
    EQ = "EQ"
    NE = "NE"
    LT = "LT"
    LE = "LE"


@dataclass(frozen=True)
class RcComparison:
    code: int
    op: CondOp


@dataclass(frozen=True)
class AllPriorSteps:
    pass


def _target(target: AllPriorSteps | R, step: Callable[[R], S]) -> AllPriorSteps | S:
    match target:
        case AllPriorSteps():
            return target
        case _:
            return step(target)


@dataclass(frozen=True)
class BypassTest(Generic[R]):
    comparison: RcComparison
    target: AllPriorSteps | R

    def mapped(self, step: Callable[[R], S]) -> BypassTest[S]:
        return BypassTest(self.comparison, _target(self.target, step))


class AbendMode(Enum):
    NORMAL = "NORMAL"
    EVEN = "EVEN"
    ONLY = "ONLY"


@dataclass(frozen=True)
class StepCondition(Generic[R]):
    bypass_tests: tuple[BypassTest[R], ...]
    abend_mode: AbendMode

    def mapped(self, step: Callable[[R], S]) -> StepCondition[S]:
        return StepCondition(
            tuple(t.mapped(step) for t in self.bypass_tests), self.abend_mode
        )


class DispStatus(Enum):
    NEW = "NEW"
    OLD = "OLD"
    SHR = "SHR"
    MOD = "MOD"


class DispNormal(Enum):
    PASS = "PASS"
    CATLG = "CATLG"
    UNCATLG = "UNCATLG"
    KEEP = "KEEP"
    DELETE = "DELETE"


class DispAbnormal(Enum):
    CATLG = "CATLG"
    UNCATLG = "UNCATLG"
    KEEP = "KEEP"
    DELETE = "DELETE"


class DatasetOrg(Enum):
    PS = "PS"
    KSDS = "KSDS"


@dataclass(frozen=True)
class Omitted:
    """A DISP subparameter left out; its default depends on whether the data set existed."""


@dataclass(frozen=True)
class ResolvedDisp:
    normal: DispNormal
    abnormal: DispAbnormal


def _existing_or_new(existed: bool) -> DispNormal:
    return DispNormal.KEEP if existed else DispNormal.DELETE


def _abnormal_default(normal: DispNormal, existed: bool) -> DispAbnormal:
    if normal is DispNormal.PASS:
        return DispAbnormal(_existing_or_new(existed).value)
    return DispAbnormal(normal.value)


@dataclass(frozen=True)
class Disp:
    status: DispStatus
    normal: DispNormal | Omitted
    abnormal: DispAbnormal | Omitted

    def disposition(self) -> Disp:
        return self

    def resolved(self, existed: bool) -> ResolvedDisp:
        normal = self._normal(existed)
        return ResolvedDisp(normal, self._abnormal(normal, existed))

    def _normal(self, existed: bool) -> DispNormal:
        match self.normal:
            case Omitted():
                return _existing_or_new(existed)
            case DispNormal():
                return self.normal

    def _abnormal(self, normal: DispNormal, existed: bool) -> DispAbnormal:
        match self.abnormal:
            case Omitted():
                return _abnormal_default(normal, existed)
            case DispAbnormal():
                return self.abnormal


@dataclass(frozen=True)
class NotCoded:
    def disposition(self) -> Disp:
        return Disp(DispStatus.NEW, Omitted(), Omitted())


def _dsn_written(
    dsn: DSN[R], in_stream: tuple[str, ...]
) -> tuple[DSN[R], tuple[str, ...]]:
    match dsn:
        case NullifiedDSN():
            return NoDSN(), ()
        case _:
            return dsn, in_stream


def _dsn_over(
    own: tuple[DSN[R], tuple[str, ...]], override: tuple[DSN[R], tuple[str, ...]]
) -> tuple[DSN[R], tuple[str, ...]]:
    match override[0]:
        case NoDSN():
            return own
        case _:
            return _dsn_written(*override)


def _disp_over(own: Disp | NotCoded, override: Disp | NotCoded) -> Disp | NotCoded:
    match override:
        case NotCoded():
            return own
        case _:
            return override


@dataclass(frozen=True)
class NullifiedValue:
    pass


def _value_over(own: Value, override: Value | NullifiedValue) -> Value:
    match override:
        case NullifiedValue():
            return ()
        case ():
            return own
        case _:
            return override


def _kept(value: Value | NullifiedValue) -> Value:
    match value:
        case NullifiedValue():
            return ()
        case _:
            return value


def _substituted_value(
    value: Value | NullifiedValue, substitution: Substitution[R]
) -> Value | NullifiedValue:
    match value:
        case NullifiedValue():
            return value
        case _:
            return substitution.value(value)


def _model_over(own: DSN[R], override: DSN[R]) -> DSN[R]:
    match override:
        case NullifiedDSN():
            return NoDSN()
        case NoDSN():
            return own
        case _:
            return override


@dataclass(frozen=True)
class Dcb(Generic[R]):
    """A DD's DCB attributes as coded: the model whose label they complete, RECFM and LRECL."""

    model: DSN[R] = NoDSN()
    recfm: Value | NullifiedValue = ()
    lrecl: Value | NullifiedValue = ()

    def overridden_by(self, override: Dcb[R]) -> Dcb[R]:
        return Dcb(
            _model_over(self.model, override.model),
            _value_over(_kept(self.recfm), override.recfm),
            _value_over(_kept(self.lrecl), override.lrecl),
        )

    def completed_by(self, referenced: Dcb[R]) -> Dcb[R]:
        return Dcb(
            NoDSN(),
            _value_over(_kept(referenced.recfm), self.recfm),
            _value_over(_kept(referenced.lrecl), self.lrecl),
        )

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> Dcb[S]:
        return Dcb(self.model.mapped(backref), self.recfm, self.lrecl)

    def substituted(self, substitution: Substitution[R]) -> Dcb[R]:
        return Dcb(
            self.model.substituted(substitution),
            _substituted_value(self.recfm, substitution),
            _substituted_value(self.lrecl, substitution),
        )


@dataclass(frozen=True)
class ConcatMember(Generic[R]):
    dsn: DSN[R]
    disp: Disp | NotCoded
    in_stream: tuple[str, ...] = ()

    def disposition(self) -> Disp:
        return self.disp.disposition()

    def overridden_by(self, override: ConcatMember[R]) -> ConcatMember[R]:
        dsn, in_stream = _dsn_over(
            (self.dsn, self.in_stream), (override.dsn, override.in_stream)
        )
        return ConcatMember(dsn, _disp_over(self.disp, override.disp), in_stream)

    def mapped(
        self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]
    ) -> ConcatMember[S]:
        return ConcatMember(self.dsn.mapped(backref), self.disp, self.in_stream)

    def substituted(self, substitution: Substitution[R]) -> ConcatMember[R]:
        return ConcatMember(
            self.dsn.substituted(substitution), self.disp, self.in_stream
        )


@dataclass(frozen=True)
class DD(Generic[R]):
    ddname: DdName
    dsn: DSN[R]
    disp: Disp | NotCoded
    in_stream: tuple[str, ...] = ()
    sysout: bool = False
    concatenated: tuple[ConcatMember[R], ...] = ()
    dcb: Dcb[R] = Dcb()
    gdg_order: Value | NullifiedValue = ()

    def disposition(self) -> Disp:
        return self.disp.disposition()

    def overridden_by(self, override: DD[R]) -> DD[R]:
        match override.dsn:
            case DummyDSN():
                return DD(
                    self.ddname,
                    override.dsn,
                    NotCoded(),
                    concatenated=self._members(override),
                    dcb=self.dcb.overridden_by(override.dcb),
                    gdg_order=_value_over(_kept(self.gdg_order), override.gdg_order),
                )
            case _:
                return self._merged(override)

    def _members(self, override: DD[R]) -> tuple[ConcatMember[R], ...]:
        own, over = self.concatenated, override.concatenated
        paired = tuple(m.overridden_by(o) for m, o in zip(own, over, strict=False))
        return (*paired, *own[len(over) :], *over[len(own) :])

    def _kept(self, override: DD[R]) -> tuple[DSN[R], tuple[str, ...]]:
        if override.sysout and isinstance(self.dsn, DummyDSN):
            return NoDSN(), ()
        return self.dsn, self.in_stream

    def _merged(self, override: DD[R]) -> DD[R]:
        dsn, in_stream = _dsn_over(
            self._kept(override), (override.dsn, override.in_stream)
        )
        excluded = override.sysout and isinstance(override.disp, NotCoded)
        disp = NotCoded() if excluded else _disp_over(self.disp, override.disp)
        sysout = override.sysout or (
            self.sysout and isinstance(override.disp, NotCoded)
        )
        return DD(
            self.ddname,
            dsn,
            disp,
            in_stream,
            sysout,
            self._members(override),
            self.dcb.overridden_by(override.dcb),
            _value_over(_kept(self.gdg_order), override.gdg_order),
        )

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> DD[S]:
        return DD(
            self.ddname,
            self.dsn.mapped(backref),
            self.disp,
            self.in_stream,
            self.sysout,
            tuple(m.mapped(backref) for m in self.concatenated),
            self.dcb.mapped(backref),
            self.gdg_order,
        )

    def substituted(self, substitution: Substitution[R]) -> DD[R]:
        return DD(
            self.ddname,
            self.dsn.substituted(substitution),
            self.disp,
            self.in_stream,
            self.sysout,
            tuple(m.substituted(substitution) for m in self.concatenated),
            self.dcb.substituted(substitution),
            _substituted_value(self.gdg_order, substitution),
        )


@dataclass(frozen=True)
class SystemAbend:
    code: int

    def rendered(self) -> str:
        return f"S{self.code:03X}"


@dataclass(frozen=True)
class UserAbend:
    code: int

    def rendered(self) -> str:
        return f"U{self.code:04d}"


@dataclass(frozen=True)
class Always:
    def mapped(self, step: Callable[[R], S]) -> Guard[S]:
        return self


@dataclass(frozen=True)
class RcTest(Generic[R]):
    target: AllPriorSteps | R
    op: CondOp
    code: int

    def mapped(self, step: Callable[[R], S]) -> Guard[S]:
        return RcTest(_target(self.target, step), self.op, self.code)


@dataclass(frozen=True)
class AbendTest(Generic[R]):
    target: AllPriorSteps | R

    def mapped(self, step: Callable[[R], S]) -> Guard[S]:
        return AbendTest(_target(self.target, step))


@dataclass(frozen=True)
class AbendCodeTest(Generic[R]):
    target: AllPriorSteps | R
    code: SystemAbend | UserAbend

    def mapped(self, step: Callable[[R], S]) -> Guard[S]:
        return AbendCodeTest(_target(self.target, step), self.code)


@dataclass(frozen=True)
class RunTest(Generic[R]):
    step: R

    def mapped(self, step: Callable[[R], S]) -> Guard[S]:
        return RunTest(step(self.step))


@dataclass(frozen=True)
class Negated(Generic[R]):
    guard: Guard[R]

    def mapped(self, step: Callable[[R], S]) -> Guard[S]:
        return Negated(self.guard.mapped(step))


@dataclass(frozen=True)
class AllOf(Generic[R]):
    guards: tuple[Guard[R], ...]

    def mapped(self, step: Callable[[R], S]) -> Guard[S]:
        return AllOf(tuple(g.mapped(step) for g in self.guards))


@dataclass(frozen=True)
class AnyOf(Generic[R]):
    guards: tuple[Guard[R], ...]

    def mapped(self, step: Callable[[R], S]) -> Guard[S]:
        return AnyOf(tuple(g.mapped(step) for g in self.guards))


Guard: TypeAlias = (
    Always
    | RcTest[R]
    | AbendTest[R]
    | AbendCodeTest[R]
    | RunTest[R]
    | Negated[R]
    | AllOf[R]
    | AnyOf[R]
)


@dataclass(frozen=True)
class ProgramStep(Generic[R]):
    label: StepLabel
    pgm: ProgramRef
    dds: tuple[DD[R], ...] = ()
    cond: StepCondition[R] = StepCondition((), AbendMode.NORMAL)
    parm: Value = ()
    guard: Guard[R] = Always()

    def mapped(
        self,
        step: Callable[[R], S],
        backref: Callable[[BackwardRef[R]], BackwardRef[S]],
    ) -> ProgramStep[S]:
        return ProgramStep(
            self.label,
            self.pgm,
            tuple(dd.mapped(backref) for dd in self.dds),
            self.cond.mapped(step),
            self.parm,
            self.guard.mapped(step),
        )


@dataclass(frozen=True)
class NotOverridden:
    pass


@dataclass(frozen=True)
class ProcStepOverrides:
    cond: StepCondition[StepRef] | NotOverridden = NotOverridden()
    parm: Value | NotOverridden = NotOverridden()
    dds: tuple[DD[StepRef], ...] = ()


@dataclass(frozen=True)
class ProcCall:
    label: StepLabel
    proc: ProcRef
    symbol_overrides: tuple[tuple[SymbolName, Value], ...] = ()
    cond_for_every_step: StepCondition[StepRef] | NotOverridden = NotOverridden()
    parm_for_first_step: Value | NotOverridden = NotOverridden()
    dds_for_first_step: tuple[DD[StepRef], ...] = ()
    per_step: tuple[tuple[StepName, ProcStepOverrides], ...] = ()


@dataclass(frozen=True)
class IfBlock:
    label: StepLabel
    condition: Guard[StepRef]
    then: tuple[JobStatement, ...]
    otherwise: tuple[JobStatement, ...] = ()


@dataclass(frozen=True)
class SetStatement:
    assignments: tuple[tuple[SymbolName, Value], ...]


@dataclass(frozen=True)
class InStreamProc:
    """PROC ... PEND inside a job: a procedure the calls after it can find before the library."""

    proc: ProcDef


JobStatement: TypeAlias = (
    ProgramStep[StepRef] | ProcCall | IfBlock | SetStatement | InStreamProc
)


@dataclass(frozen=True)
class Job:
    name: str
    steps: tuple[JobStatement, ...]
    end_job_tests: tuple[RcComparison, ...] = ()


@dataclass(frozen=True)
class ProcDef:
    name: str
    defaults: tuple[tuple[SymbolName, Value], ...]
    steps: tuple[JobStatement, ...]


def _rendered(coordinates: tuple[ResolvedProcCall, ...], last: StepLabel) -> str:
    labels = (*(c.call.label for c in coordinates), last)
    return ".".join(label.rendered() for label in labels)


@dataclass(frozen=True)
class QualifiedStep:
    coordinates: tuple[ResolvedProcCall, ...]
    step: ProgramStep[StepReference]

    def rendered(self) -> str:
        return _rendered(self.coordinates, self.step.label)

    def reference(self) -> StepReference:
        return StepReference(self.coordinates, ResolvedProgramStep(self.step))


@dataclass(frozen=True)
class UnexpandedCall:
    coordinates: tuple[ResolvedProcCall, ...]

    def call(self) -> ProcCall:
        return self.coordinates[-1].call

    def rendered(self) -> str:
        return _rendered(self.coordinates[:-1], self.call().label)
