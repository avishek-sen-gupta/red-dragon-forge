"""The JCL bridge's JSON contract as Pydantic models, each building its part of the job model."""

from collections.abc import Sequence
from itertools import chain
from typing import Annotated, Literal

from jackal.dsn import (
    DSN,
    BackwardRef,
    DirectDSN,
    DummyDSN,
    InStreamDSN,
    NoDSN,
    TempRef,
)
from jackal.model import (
    DD,
    CondOp,
    Disp,
    DispNormal,
    DispStatus,
    Job,
    ProcDef,
    Step,
)
from jackal.model import (
    Cond as ModelCond,
)
from pydantic import BaseModel, ConfigDict, Field, RootModel

from jackal import value_parts

_PREEXISTING_STATUSES = frozenset({DispStatus.OLD, DispStatus.SHR, DispStatus.MOD})


def disp_from_words(words: tuple[str, ...]) -> Disp:
    """``DISP=(status,normal,abnormal)``, with any subparameter omissible.

    An omitted positional subparameter arrives as ``""`` (the bridge keeps the
    slot); a DD with no ``DISP=`` at all arrives as ``()``. The z/OS defaults are
    positional and chained rather than one fixed triple: the status defaults to
    NEW, the normal disposition to DELETE for a data set this step creates and
    KEEP for one that already existed, and the abnormal disposition to whichever
    normal disposition resolved. So a DD with no ``DISP=`` is (NEW,DELETE,DELETE)
    by the same rule, not by a separate constant.

    MOD is read as already-existing. It can be either — MOD creates the data set
    when it is absent and appends when it is present — and JCL alone cannot say
    which.
    """

    def slot(i: int) -> str:
        return words[i] if i < len(words) else ""

    status = DispStatus(slot(0)) if slot(0) else DispStatus.NEW
    default_normal = (
        DispNormal.KEEP if status in _PREEXISTING_STATUSES else DispNormal.DELETE
    )
    normal = DispNormal(slot(1)) if slot(1) else default_normal
    abnormal = DispNormal(slot(2)) if slot(2) else normal
    return Disp(status, normal, abnormal)


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
        return value_parts.Symbol(self.name)


Part = Annotated[LiteralPart | SymbolPart, Field(discriminator="kind")]


def value(parts: Sequence[LiteralPart | SymbolPart]) -> value_parts.Value:
    return tuple(p.part() for p in parts)


class AllPrior(Wire):
    kind: Literal["all_prior"] = "all_prior"

    def cond_step(self) -> str:
        return ""

    def backward_ref(self, ddname: str) -> DSN:
        raise ValueError(f"a backward reference to {ddname} names no step")


class StepTarget(Wire):
    kind: Literal["step"] = "step"
    step: str

    def cond_step(self) -> str:
        return self.step

    def backward_ref(self, ddname: str) -> DSN:
        return BackwardRef(step=self.step, ddname=ddname)


class ProcStepTarget(Wire):
    kind: Literal["proc_step"] = "proc_step"
    call: str
    step: str

    def cond_step(self) -> str:
        return f"{self.call}.{self.step}"

    def backward_ref(self, ddname: str) -> DSN:
        raise ValueError(
            f"Three-segment backward reference '*.{self.call}.{self.step}.{ddname}' "
            "is not yet supported (see jackal-lz8 — requires PROC support from "
            "jackal-1o2.2)"
        )


Target = Annotated[AllPrior | StepTarget | ProcStepTarget, Field(discriminator="kind")]

Op = Literal["GT", "GE", "EQ", "NE", "LT", "LE"]


class CondTest(Wire):
    code: int
    op: Op
    target: Target


class Cond(Wire):
    tests: tuple[CondTest, ...]
    mode: Literal["NORMAL", "EVEN", "ONLY"]

    def conds(self) -> tuple[ModelCond, ...]:
        if self.mode != "NORMAL":
            raise ValueError(f"COND={self.mode} is not supported (jackal-1o2.8)")
        return tuple(
            ModelCond(t.code, CondOp(t.op), t.target.cond_step()) for t in self.tests
        )


class RcComparison(Wire):
    code: int
    op: Op


class NameDsn(Wire):
    kind: Literal["name"] = "name"
    value: tuple[Part, ...]

    def model(self) -> DSN:
        return DirectDSN(value(self.value))


class TempDsn(Wire):
    kind: Literal["temp"] = "temp"
    name: str

    def model(self) -> DSN:
        return TempRef(f"&&{self.name}")


class BackrefDsn(Wire):
    kind: Literal["backref"] = "backref"
    target: Target
    ddname: str

    def model(self) -> DSN:
        return self.target.backward_ref(self.ddname)


class InStreamDsn(Wire):
    kind: Literal["in_stream"] = "in_stream"

    def model(self) -> DSN:
        return InStreamDSN()


class DummyDsn(Wire):
    kind: Literal["dummy"] = "dummy"

    def model(self) -> DSN:
        return DummyDSN()


class NoneDsn(Wire):
    kind: Literal["none"] = "none"

    def model(self) -> DSN:
        return NoDSN()


Dsn = Annotated[
    NameDsn | TempDsn | BackrefDsn | InStreamDsn | DummyDsn | NoneDsn,
    Field(discriminator="kind"),
]


class Member(Wire):
    dsn: Dsn
    disp: tuple[str, ...]
    in_stream: tuple[str, ...]


class Dd(Wire):
    ddname: str
    dsn: Dsn
    disp: tuple[str, ...]
    in_stream: tuple[str, ...]
    sysout: bool
    concatenated: tuple[Member, ...]

    def model(self, ddname: str) -> DD:
        return DD(
            ddname=ddname,
            dsn=self.dsn.model(),
            disp=disp_from_words(self.disp),
            in_stream=self.in_stream,
            sysout=self.sysout,
        )


class SymbolValue(Wire):
    name: str
    value: tuple[Part, ...]


class ParmOverride(Wire):
    procstep: str
    parm: tuple[Part, ...]


class CondOverride(Wire):
    procstep: str
    cond: Cond


class DdOverride(Wire):
    procstep: str
    dd: Dd

    def model(self) -> DD:
        if self.procstep:
            return self.dd.model(f"{self.procstep}.{self.dd.ddname}")
        return self.dd.model(self.dd.ddname)


class SystemCode(Wire):
    kind: Literal["system"] = "system"
    code: int


class UserCode(Wire):
    kind: Literal["user"] = "user"
    code: int


class RcExpr(Wire):
    kind: Literal["rc"] = "rc"
    target: Target
    op: Op
    code: int


class AbendExpr(Wire):
    kind: Literal["abend"] = "abend"
    target: Target


class RunExpr(Wire):
    kind: Literal["run"] = "run"
    target: Target


class AbendCodeExpr(Wire):
    kind: Literal["abend_code"] = "abend_code"
    target: Target
    abend: Annotated[SystemCode | UserCode, Field(discriminator="kind")]


class NotExpr(Wire):
    kind: Literal["not"] = "not"
    operand: "Expr"


class AndExpr(Wire):
    kind: Literal["and"] = "and"
    operands: tuple["Expr", ...]


class OrExpr(Wire):
    kind: Literal["or"] = "or"
    operands: tuple["Expr", ...]


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

    def steps(self) -> tuple[Step, ...]:
        return (
            Step(
                name=self.label,
                pgm=self.pgm,
                dds=tuple(dd.model(dd.ddname) for dd in self.dds),
                conds=self.cond.conds(),
                parm=value(self.parm),
            ),
        )


class ProcCall(Wire):
    kind: Literal["proc_call"] = "proc_call"
    label: str
    proc: str
    symbol_overrides: tuple[SymbolValue, ...]
    parm_overrides: tuple[ParmOverride, ...]
    cond_overrides: tuple[CondOverride, ...]
    dd_overrides: tuple[DdOverride, ...]

    def steps(self) -> tuple[Step, ...]:
        return (
            Step(
                name=self.label,
                pgm=self.proc,
                dds=tuple(o.model() for o in self.dd_overrides),
                conds=next((o.cond.conds() for o in self.cond_overrides), ()),
                parm=next((value(o.parm) for o in self.parm_overrides), ()),
                proc_parms={s.name: value(s.value) for s in self.symbol_overrides},
            ),
        )


class IfBlock(Wire):
    kind: Literal["if"] = "if"
    label: str
    condition: Expr
    then: tuple["Statement", ...]
    otherwise: tuple["Statement", ...]

    def steps(self) -> tuple[Step, ...]:
        return all_steps((*self.then, *self.otherwise))


Statement = Annotated[Program | ProcCall | IfBlock, Field(discriminator="kind")]


def all_steps(statements: Sequence[Program | ProcCall | IfBlock]) -> tuple[Step, ...]:
    return tuple(chain.from_iterable(s.steps() for s in statements))


class JobDoc(Wire):
    kind: Literal["job"] = "job"
    name: str
    end_job_tests: tuple[RcComparison, ...]
    statements: tuple[Statement, ...]

    def job(self) -> Job:
        return Job(
            name=self.name,
            steps=all_steps(self.statements),
            cond=tuple(ModelCond(t.code, CondOp(t.op)) for t in self.end_job_tests),
        )

    def proc(self) -> ProcDef:
        return ProcDef(name=self.name, defaults={}, steps=all_steps(self.statements))


class ProcDoc(Wire):
    kind: Literal["proc"] = "proc"
    name: str
    defaults: tuple[SymbolValue, ...]
    statements: tuple[Statement, ...]

    def job(self) -> Job:
        return Job(name=self.name, steps=all_steps(self.statements))

    def proc(self) -> ProcDef:
        return ProcDef(
            name=self.name,
            defaults={d.name: value(d.value) for d in self.defaults},
            steps=all_steps(self.statements),
        )


class Document(RootModel[Annotated[JobDoc | ProcDoc, Field(discriminator="kind")]]):
    model_config = ConfigDict(frozen=True)
