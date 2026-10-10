"""The JCL bridge's JSON contract as Pydantic models, each building its part of the parsed job model."""

from collections.abc import Sequence
from itertools import accumulate
from typing import Annotated, Literal

from jackal.model import (
    DSN,
    AbendMode,
    BackwardRef,
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
    StepRef,
    TempRef,
)
from pydantic import BaseModel, ConfigDict, Field, RootModel

from jackal import model, value_parts

_PREEXISTING_STATUSES = frozenset({DispStatus.OLD, DispStatus.SHR, DispStatus.MOD})


def _default_abnormal(status: DispStatus, normal: DispNormal) -> DispAbnormal:
    if normal is DispNormal.PASS:
        return DispAbnormal.DELETE if status is DispStatus.NEW else DispAbnormal.KEEP
    return DispAbnormal(normal.value)


def disp_from_words(words: tuple[str, ...]) -> Disp:

    def slot(i: int) -> str:
        return words[i] if i < len(words) else ""

    status = DispStatus(slot(0)) if slot(0) else DispStatus.NEW
    default_normal = (
        DispNormal.KEEP if status in _PREEXISTING_STATUSES else DispNormal.DELETE
    )
    normal = DispNormal(slot(1)) if slot(1) else default_normal
    abnormal = DispAbnormal(slot(2)) if slot(2) else _default_abnormal(status, normal)
    return Disp(status, normal, abnormal)


def _label(text: str) -> model.StepLabel:
    return model.StepName(text) if text else model.Unnamed()


class Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LiteralPart(Wire):
    kind: Literal["literal"] = "literal"
    text: str

    def part(self) -> value_parts.ValuePart:
        return value_parts.Literal(self.text)


class SymbolPart(Wire):
    kind: Literal["symbol"] = "symbol"
    name: str

    def part(self) -> value_parts.ValuePart:
        return value_parts.Symbol(value_parts.SymbolName(self.name))


Part = Annotated[LiteralPart | SymbolPart, Field(discriminator="kind")]


def value(parts: Sequence[LiteralPart | SymbolPart]) -> value_parts.Value:
    return tuple(p.part() for p in parts)


class AllPrior(Wire):
    kind: Literal["all_prior"] = "all_prior"

    def cond_target(self) -> model.AllPriorSteps | StepRef:
        return model.AllPriorSteps()

    def step_ref(self) -> StepRef:
        raise ValueError("this reference must name a step")


class StepTarget(Wire):
    kind: Literal["step"] = "step"
    step: str

    def cond_target(self) -> model.AllPriorSteps | StepRef:
        return self.step_ref()

    def step_ref(self) -> StepRef:
        return StepRef(model.OwnScope(), model.StepName(self.step))


class ProcStepTarget(Wire):
    kind: Literal["proc_step"] = "proc_step"
    call: str
    step: str

    def cond_target(self) -> model.AllPriorSteps | StepRef:
        return self.step_ref()

    def step_ref(self) -> StepRef:
        return StepRef(
            model.CalledProcScope(model.StepName(self.call)),
            model.StepName(self.step),
        )


Target = Annotated[AllPrior | StepTarget | ProcStepTarget, Field(discriminator="kind")]

Op = Literal["GT", "GE", "EQ", "NE", "LT", "LE"]


class CondTest(Wire):
    code: int
    op: Op
    target: Target

    def bypass_test(self) -> model.BypassTest[StepRef]:
        return model.BypassTest(
            model.RcComparison(self.code, CondOp(self.op)), self.target.cond_target()
        )


class Cond(Wire):
    tests: tuple[CondTest, ...]
    mode: Literal["NORMAL", "EVEN", "ONLY"]

    def condition(self) -> model.StepCondition[StepRef]:
        return model.StepCondition(
            tuple(t.bypass_test() for t in self.tests), AbendMode(self.mode)
        )


class RcComparison(Wire):
    code: int
    op: Op

    def comparison(self) -> model.RcComparison:
        return model.RcComparison(self.code, CondOp(self.op))


class NameDsn(Wire):
    kind: Literal["name"] = "name"
    value: tuple[Part, ...]

    def model(self) -> DSN[StepRef]:
        return DirectDSN(value(self.value))


class TempDsn(Wire):
    kind: Literal["temp"] = "temp"
    name: str

    def model(self) -> DSN[StepRef]:
        return TempRef(self.name)


class BackrefDsn(Wire):
    kind: Literal["backref"] = "backref"
    target: Target
    ddname: str

    def model(self) -> DSN[StepRef]:
        return BackwardRef(
            self.target.step_ref(), model.UnresolvedDd(DdName(self.ddname))
        )


class InStreamDsn(Wire):
    kind: Literal["in_stream"] = "in_stream"

    def model(self) -> DSN[StepRef]:
        return InStreamDSN()


class DummyDsn(Wire):
    kind: Literal["dummy"] = "dummy"

    def model(self) -> DSN[StepRef]:
        return DummyDSN()


class NoneDsn(Wire):
    kind: Literal["none"] = "none"

    def model(self) -> DSN[StepRef]:
        return NoDSN()


Dsn = Annotated[
    NameDsn | TempDsn | BackrefDsn | InStreamDsn | DummyDsn | NoneDsn,
    Field(discriminator="kind"),
]


class Member(Wire):
    dsn: Dsn
    disp: tuple[str, ...]
    in_stream: tuple[str, ...]

    def model(self) -> model.ConcatMember[StepRef]:
        return model.ConcatMember(
            self.dsn.model(), disp_from_words(self.disp), self.in_stream
        )


class Dd(Wire):
    ddname: str
    dsn: Dsn
    disp: tuple[str, ...]
    in_stream: tuple[str, ...]
    sysout: bool
    concatenated: tuple[Member, ...]

    def model(self) -> model.DD[StepRef]:
        return model.DD(
            DdName(self.ddname),
            self.dsn.model(),
            disp_from_words(self.disp),
            self.in_stream,
            self.sysout,
            tuple(m.model() for m in self.concatenated),
        )


class SymbolValue(Wire):
    name: str
    value: tuple[Part, ...]

    def binding(self) -> tuple[value_parts.SymbolName, value_parts.Value]:
        return (value_parts.SymbolName(self.name), value(self.value))


class ParmOverride(Wire):
    procstep: str
    parm: tuple[Part, ...]


class CondOverride(Wire):
    procstep: str
    cond: Cond


class DdOverride(Wire):
    procstep: str
    dd: Dd


class SystemCode(Wire):
    kind: Literal["system"] = "system"
    code: int

    def abend(self) -> model.SystemAbend | model.UserAbend:
        return model.SystemAbend(self.code)


class UserCode(Wire):
    kind: Literal["user"] = "user"
    code: int

    def abend(self) -> model.SystemAbend | model.UserAbend:
        return model.UserAbend(self.code)


class RcExpr(Wire):
    kind: Literal["rc"] = "rc"
    target: Target
    op: Op
    code: int

    def guard(self) -> model.Guard[StepRef]:
        return model.RcTest(self.target.cond_target(), CondOp(self.op), self.code)


class AbendExpr(Wire):
    kind: Literal["abend"] = "abend"
    target: Target

    def guard(self) -> model.Guard[StepRef]:
        return model.AbendTest(self.target.cond_target())


class RunExpr(Wire):
    kind: Literal["run"] = "run"
    target: Target

    def guard(self) -> model.Guard[StepRef]:
        return model.RunTest(self.target.step_ref())


class AbendCodeExpr(Wire):
    kind: Literal["abend_code"] = "abend_code"
    target: Target
    abend: Annotated[SystemCode | UserCode, Field(discriminator="kind")]

    def guard(self) -> model.Guard[StepRef]:
        return model.AbendCodeTest(self.target.cond_target(), self.abend.abend())


class NotExpr(Wire):
    kind: Literal["not"] = "not"
    operand: "Expr"

    def guard(self) -> model.Guard[StepRef]:
        return model.Negated(self.operand.guard())


class AndExpr(Wire):
    kind: Literal["and"] = "and"
    operands: tuple["Expr", ...]

    def guard(self) -> model.Guard[StepRef]:
        return model.AllOf(tuple(o.guard() for o in self.operands))


class OrExpr(Wire):
    kind: Literal["or"] = "or"
    operands: tuple["Expr", ...]

    def guard(self) -> model.Guard[StepRef]:
        return model.AnyOf(tuple(o.guard() for o in self.operands))


Expr = Annotated[
    RcExpr | AbendExpr | RunExpr | AbendCodeExpr | NotExpr | AndExpr | OrExpr,
    Field(discriminator="kind"),
]


class Program(Wire):
    kind: Literal["program"] = "program"
    label: str
    pgm: str
    parm: tuple[Part, ...]
    cond: Cond
    dds: tuple[Dd, ...]

    def statement(self) -> model.JobStatement:
        return model.ProgramStep(
            _label(self.label),
            model.ProgramRef(self.pgm),
            tuple(dd.model() for dd in self.dds),
            self.cond.condition(),
            value(self.parm),
        )


def _last_parm(
    overrides: Sequence[ParmOverride], procstep: str
) -> value_parts.Value | model.NotOverridden:
    matching = [value(o.parm) for o in overrides if o.procstep == procstep]
    return matching[-1] if matching else model.NotOverridden()


def _last_cond(
    overrides: Sequence[CondOverride], procstep: str
) -> model.StepCondition[StepRef] | model.NotOverridden:
    matching = [o.cond.condition() for o in overrides if o.procstep == procstep]
    return matching[-1] if matching else model.NotOverridden()


def _unique(names: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(n for n in names if n))


class ProcCall(Wire):
    kind: Literal["proc_call"] = "proc_call"
    label: str
    proc: str
    symbol_overrides: tuple[SymbolValue, ...]
    parm_overrides: tuple[ParmOverride, ...]
    cond_overrides: tuple[CondOverride, ...]
    dd_overrides: tuple[DdOverride, ...]

    def _dd_targets(self) -> tuple[str, ...]:
        return tuple(
            accumulate(
                (o.procstep for o in self.dd_overrides), lambda prev, cur: cur or prev
            )
        )

    def _dds_for(self, procstep: str) -> tuple[model.DD[StepRef], ...]:
        return tuple(
            o.dd.model()
            for o, target in zip(self.dd_overrides, self._dd_targets(), strict=True)
            if target == procstep
        )

    def _per_step(self, procstep: str) -> model.ProcStepOverrides:
        return model.ProcStepOverrides(
            _last_cond(self.cond_overrides, procstep),
            _last_parm(self.parm_overrides, procstep),
            self._dds_for(procstep),
        )

    def statement(self) -> model.JobStatement:
        procsteps = _unique(
            (
                *(o.procstep for o in self.parm_overrides),
                *(o.procstep for o in self.cond_overrides),
                *self._dd_targets(),
            )
        )
        return model.ProcCall(
            _label(self.label),
            model.ProcRef(self.proc),
            tuple(s.binding() for s in self.symbol_overrides),
            _last_cond(self.cond_overrides, ""),
            _last_parm(self.parm_overrides, ""),
            self._dds_for(""),
            tuple((model.StepName(p), self._per_step(p)) for p in procsteps),
        )


class IfBlock(Wire):
    kind: Literal["if"] = "if"
    label: str
    condition: Expr
    then: tuple["Statement", ...]
    otherwise: tuple["Statement", ...]

    def statement(self) -> model.JobStatement:
        return model.IfBlock(
            _label(self.label),
            self.condition.guard(),
            statements(self.then),
            statements(self.otherwise),
        )


class SetStatement(Wire):
    kind: Literal["set"] = "set"
    assignments: tuple[SymbolValue, ...]

    def statement(self) -> model.JobStatement:
        return model.SetStatement(tuple(a.binding() for a in self.assignments))


Statement = Annotated[
    Program | ProcCall | IfBlock | SetStatement, Field(discriminator="kind")
]


def statements(
    wired: Sequence[Program | ProcCall | IfBlock | SetStatement],
) -> tuple[model.JobStatement, ...]:
    return tuple(s.statement() for s in wired)


class JobDoc(Wire):
    kind: Literal["job"] = "job"
    name: str
    end_job_tests: tuple[RcComparison, ...]
    statements: tuple[Statement, ...]

    def job(self) -> model.Job:
        return model.Job(
            self.name,
            statements(self.statements),
            tuple(t.comparison() for t in self.end_job_tests),
        )

    def proc(self) -> model.ProcDef:
        return model.ProcDef(self.name, (), statements(self.statements))


class ProcDoc(Wire):
    kind: Literal["proc"] = "proc"
    name: str
    defaults: tuple[SymbolValue, ...]
    statements: tuple[Statement, ...]

    def job(self) -> model.Job:
        return model.Job(self.name, statements(self.statements))

    def proc(self) -> model.ProcDef:
        return model.ProcDef(
            self.name,
            tuple(d.binding() for d in self.defaults),
            statements(self.statements),
        )


class Document(RootModel[Annotated[JobDoc | ProcDoc, Field(discriminator="kind")]]):
    model_config = ConfigDict(frozen=True)
