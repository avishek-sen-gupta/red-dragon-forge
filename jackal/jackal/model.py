"""The JCL job model: what a job says, parsed, and each step once PROC calls are expanded."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeAlias, TypeVar

from jackal.dsn import DSN, BackwardRef, DdName
from jackal.value_parts import SymbolName, Value

R = TypeVar("R", bound="StepRef | QualifiedStep")
S = TypeVar("S", bound="StepRef | QualifiedStep")


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
class Disp:
    status: DispStatus
    normal: DispNormal
    abnormal: DispAbnormal


@dataclass(frozen=True)
class ConcatMember(Generic[R]):
    dsn: DSN[R]
    disp: Disp
    in_stream: tuple[str, ...] = ()

    def mapped(
        self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]
    ) -> ConcatMember[S]:
        return ConcatMember(self.dsn.mapped(backref), self.disp, self.in_stream)

    def substituted(self, name: Callable[[Value], DSN[R]]) -> ConcatMember[R]:
        return ConcatMember(self.dsn.substituted(name), self.disp, self.in_stream)


@dataclass(frozen=True)
class DD(Generic[R]):
    ddname: DdName
    dsn: DSN[R]
    disp: Disp
    in_stream: tuple[str, ...] = ()
    sysout: bool = False
    concatenated: tuple[ConcatMember[R], ...] = ()

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> DD[S]:
        return DD(
            self.ddname,
            self.dsn.mapped(backref),
            self.disp,
            self.in_stream,
            self.sysout,
            tuple(m.mapped(backref) for m in self.concatenated),
        )

    def substituted(self, name: Callable[[Value], DSN[R]]) -> DD[R]:
        return DD(
            self.ddname,
            self.dsn.substituted(name),
            self.disp,
            self.in_stream,
            self.sysout,
            tuple(m.substituted(name) for m in self.concatenated),
        )


@dataclass(frozen=True)
class SystemAbend:
    code: int


@dataclass(frozen=True)
class UserAbend:
    code: int


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

    def step_label(self) -> StepLabel:
        return self.label

    def runs_program(self) -> bool:
        return True

    def dd_names(self) -> frozenset[DdName]:
        return frozenset(dd.ddname for dd in self.dds)

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


JobStatement: TypeAlias = ProgramStep[StepRef] | ProcCall | IfBlock


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


@dataclass(frozen=True)
class UnresolvedProcCall:
    call: ProcCall

    def step_label(self) -> StepLabel:
        return self.call.label

    def runs_program(self) -> bool:
        return False

    def dd_names(self) -> frozenset[DdName]:
        return frozenset()


@dataclass(frozen=True)
class QualifiedStep:
    calls: tuple[ProcCall, ...]
    step: ProgramStep[QualifiedStep] | UnresolvedProcCall

    def rendered(self) -> str:
        labels = (*(c.label for c in self.calls), self.step.step_label())
        return ".".join(label.rendered() for label in labels)
