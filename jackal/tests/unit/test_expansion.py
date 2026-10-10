"""expand_procs on jobs built in code, with an in-memory PROC library."""

from dataclasses import dataclass

from jackal.expansion import ExpandedJob, ProcLibrary, ProcNotFound, expand_procs
from jackal.model import (
    ResolvedProc,
    ResolvedProcCall,
    DirectDSN,
    ProcCall,
    ProcDef,
    ProcRef,
    QualifiedStep,
    StepName,
    TempRef,
)
from jackal.value_parts import Literal, Symbol, SymbolName, literal
from tests.covers import NotLanguageFeature, covers
from tests.model_build import dd, job, program


@dataclass(frozen=True)
class _Library(ProcLibrary):
    procs: tuple[ProcDef, ...]

    def find(self, proc: ProcRef) -> ProcDef | ProcNotFound:
        found = tuple(p for p in self.procs if p.name == proc.name)
        return found[0] if found else ProcNotFound()


def _symbol(name: str) -> Symbol:
    return Symbol(SymbolName(name))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_only_a_lone_unbound_symbol_short_enough_for_a_qualifier_is_a_temp():
    lone = DirectDSN((_symbol("WORK"),))
    glued = DirectDSN((_symbol("HLQ"), Literal(".DATA")))
    too_long = DirectDSN((_symbol("WORKAREA1"),))
    step = program("S1", "PGMA", (dd("A", lone), dd("B", glued), dd("C", too_long)))
    expanded = expand_procs(job("J", (step,)), _Library(()))
    assert isinstance(expanded, ExpandedJob)
    assert [d.dsn for d in expanded.steps[0].step.dds] == [
        TempRef("WORK"),
        glued,
        too_long,
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_symbols_resolve_against_the_call_then_the_defaults_and_unbound_ones_stay():
    proc = ProcDef(
        "P",
        ((SymbolName("HLQ"), literal("TEST")), (SymbolName("SUF"), literal("X"))),
        (
            program(
                "P1",
                "PGMA",
                (
                    dd("IN", DirectDSN((_symbol("HLQ"), Literal(".DATA.")))),
                    dd(
                        "OUT",
                        DirectDSN((_symbol("SUF"), Literal("."), _symbol("NOPE"))),
                    ),
                ),
            ),
        ),
    )
    call = ProcCall(
        StepName("S1"), ProcRef("P"), ((SymbolName("HLQ"), literal("PROD")),)
    )
    expanded = expand_procs(job("J", (call,)), _Library((proc,)))
    assert expanded == ExpandedJob(
        "J",
        (
            QualifiedStep(
                (ResolvedProcCall(call, ResolvedProc(proc)),),
                program(
                    "P1",
                    "PGMA",
                    (
                        dd("IN", DirectDSN(literal("PROD.DATA."))),
                        dd("OUT", DirectDSN((Literal("X."), _symbol("NOPE")))),
                    ),
                ),
            ),
        ),
    )


def _named(label: str, pgm: str, dds=()) -> object:
    return program(label, pgm, dds)


def _ref(step: str) -> object:
    from jackal.model import OwnScope, StepRef

    return StepRef(OwnScope(), StepName(step))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_an_if_guard_resolves_where_the_if_was_written():
    from jackal.model import CondOp, IfBlock, ProgramStep, RcTest

    proc = ProcDef(
        "MYP", (), (_named("STEP0", "P0"), _named("STEP1", "P1"), _named("STEP2", "P2"))
    )
    call = ProcCall(StepName("CALL"), ProcRef("MYP"))
    j = job(
        "J",
        (
            _named("STEP1", "A"),
            IfBlock(StepName("C1"), RcTest(_ref("STEP1"), CondOp.EQ, 0), (call,)),
        ),
    )
    expanded = expand_procs(j, _Library((proc,)))
    job_step1 = expanded.steps[0]
    guard = RcTest(job_step1.reference(), CondOp.EQ, 0)
    assert [q.step.guard for q in expanded.steps[1:]] == [guard, guard, guard]
    assert isinstance(expanded.steps[1].step, ProgramStep)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_reference_written_in_a_proc_reaches_its_steps_from_a_nested_proc():
    from jackal.model import (
        BackwardRef,
        CondOp,
        DdName,
        IfBlock,
        ProcStepOverrides,
        RcTest,
        ResolvedDd,
        UnresolvedDd,
    )

    inner = ProcDef("B", (), (_named("BS1", "PB"),))
    nested_call = ProcCall(
        StepName("CB"),
        ProcRef("B"),
        per_step=(
            (
                StepName("BS1"),
                ProcStepOverrides(
                    dds=(
                        dd(
                            "IN",
                            BackwardRef(_ref("AS1"), UnresolvedDd(DdName("DD1"))),
                        ),
                    )
                ),
            ),
        ),
    )
    outer = ProcDef(
        "A",
        (),
        (
            _named("AS1", "PA", (dd("DD1", "T.A"),)),
            IfBlock(StepName("I1"), RcTest(_ref("AS1"), CondOp.EQ, 0), (nested_call,)),
        ),
    )
    j = job("J", (ProcCall(StepName("C1"), ProcRef("A")),))
    expanded = expand_procs(j, _Library((outer, inner)))
    as1, bs1 = expanded.steps
    assert bs1.step.guard == RcTest(as1.reference(), CondOp.EQ, 0)
    assert bs1.step.dds[0].dsn == BackwardRef(
        as1.reference(), ResolvedDd(as1.step.dds[0])
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_an_override_that_lands_on_a_nested_proc_call_is_an_error():
    from jackal.expansion import OverrideNamesNoStep
    from jackal.model import ProcStepOverrides

    inner = ProcDef("B", (), (_named("BS1", "PB"),))
    outer = ProcDef(
        "A", (), (ProcCall(StepName("CB"), ProcRef("B")), _named("AS2", "Z"))
    )
    library = _Library((outer, inner))
    qualified = ProcCall(
        StepName("C1"),
        ProcRef("A"),
        per_step=((StepName("CB"), ProcStepOverrides(parm=literal("X"))),),
    )
    first = ProcCall(StepName("C1"), ProcRef("A"), parm_for_first_step=literal("HELLO"))
    assert [
        expand_procs(job("J", (qualified,)), library),
        expand_procs(job("J", (first,)), library),
    ] == [
        OverrideNamesNoStep(qualified, StepName("CB")),
        OverrideNamesNoStep(first, StepName("CB")),
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_default_that_names_another_default_resolves_through_it():
    proc = ProcDef(
        "P",
        ((SymbolName("A"), literal("REAL.DS")), (SymbolName("B"), (_symbol("A"),))),
        (_named("S", "PGMA", (dd("IN", DirectDSN((_symbol("B"),))),)),),
    )
    expanded = expand_procs(
        job("J", (ProcCall(StepName("C1"), ProcRef("P")),)), _Library((proc,))
    )
    assert expanded.steps[0].step.dds[0].dsn == DirectDSN(literal("REAL.DS"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_only_the_first_step_by_position_takes_the_first_step_parm():
    from jackal.model import ProgramRef, ProgramStep, Unnamed

    proc = ProcDef(
        "P",
        (),
        (
            ProgramStep(Unnamed(), ProgramRef("PGMA")),
            ProgramStep(Unnamed(), ProgramRef("PGMB")),
        ),
    )
    call = ProcCall(StepName("C1"), ProcRef("P"), parm_for_first_step=literal("HELLO"))
    expanded = expand_procs(job("J", (call,)), _Library((proc,)))
    assert [q.step.parm for q in expanded.steps] == [literal("HELLO"), ()]
