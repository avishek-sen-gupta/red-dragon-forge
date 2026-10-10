from jackal.jcl import wire
from jackal.jcl.bridge_parser import job_from_bridge_json
from jackal.model import (
    UnresolvedDd,
    DD,
    AbendMode,
    AllPriorSteps,
    BackwardRef,
    BypassTest,
    CalledProcScope,
    CondOp,
    DdName,
    DirectDSN,
    DummyDSN,
    InStreamDSN,
    Job,
    NoDSN,
    NotOverridden,
    OwnScope,
    ProcCall,
    ProcRef,
    ProcStepOverrides,
    ProgramRef,
    ProgramStep,
    RcComparison,
    StepCondition,
    StepName,
    StepRef,
    TempRef,
)
from jackal.value_parts import Literal, Symbol, SymbolName, literal
from tests.covers import NotLanguageFeature, covers
from tests.model_build import disp
from tests.wire_build import cond_test, dd, job_json, lit, name_dsn, program, sym


def _dd(name: str, dsn: object, d: object, **rest: object) -> object:
    return DD(DdName(name), dsn, d, **rest)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_program_step_with_each_dsn_kind():
    out = job_json(
        "PIPE",
        (
            program(
                "STEP1",
                "UPCASE",
                (
                    dd("IN", name_dsn("J.IN"), ("SHR",)),
                    dd("HLQ", wire.NameDsn(value=(sym("HLQ"), lit(".X"))), ("SHR",)),
                    dd("WRK", wire.TempDsn(name="WORK"), ("NEW", "PASS")),
                    dd("SYSIN", wire.InStreamDsn(), in_stream=(" CARD",)),
                    dd("NULL", wire.DummyDsn()),
                    dd("REPORT", sysout=True),
                    dd(
                        "PCOPY",
                        wire.BackrefDsn(
                            target=wire.ProcStepTarget(call="S0", step="P1"),
                            ddname="IN",
                        ),
                        ("OLD", "DELETE"),
                    ),
                ),
            ),
        ),
    )
    p1 = StepRef(CalledProcScope(StepName("S0")), StepName("P1"))
    assert job_from_bridge_json(out) == Job(
        "PIPE",
        (
            ProgramStep(
                StepName("STEP1"),
                ProgramRef("UPCASE"),
                (
                    _dd("IN", DirectDSN(literal("J.IN")), disp("SHR")),
                    _dd(
                        "HLQ",
                        DirectDSN((Symbol(SymbolName("HLQ")), Literal(".X"))),
                        disp("SHR"),
                    ),
                    _dd("WRK", TempRef("WORK"), disp("NEW", "PASS", "DELETE")),
                    _dd("SYSIN", InStreamDSN(), disp(), in_stream=(" CARD",)),
                    _dd("NULL", DummyDSN(), disp()),
                    _dd("REPORT", NoDSN(), disp(), sysout=True),
                    _dd(
                        "PCOPY",
                        BackwardRef(p1, UnresolvedDd(DdName("IN"))),
                        disp("OLD", "DELETE"),
                    ),
                ),
            ),
        ),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cond_tests_mode_and_end_job_tests():
    out = job_json(
        "J",
        (
            program(
                "S",
                "P",
                cond=wire.Cond(
                    tests=(cond_test(4, "LT", "A"), cond_test(8, "EQ")), mode="EVEN"
                ),
            ),
        ),
        end_job_tests=(wire.RcComparison(code=0, op="NE"),),
    )
    assert job_from_bridge_json(out) == Job(
        "J",
        (
            ProgramStep(
                StepName("S"),
                ProgramRef("P"),
                cond=StepCondition(
                    (
                        BypassTest(
                            RcComparison(4, CondOp.LT),
                            StepRef(OwnScope(), StepName("A")),
                        ),
                        BypassTest(RcComparison(8, CondOp.EQ), AllPriorSteps()),
                    ),
                    AbendMode.EVEN,
                ),
            ),
        ),
        end_job_tests=(RcComparison(0, CondOp.NE),),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_proc_calls_overrides_group_by_step_and_unqualified_dds_follow_the_last_qualifier():
    def override_dd(procstep: str, name: str) -> wire.DdOverride:
        return wire.DdOverride(procstep=procstep, dd=dd(name, name_dsn(f"T.{name}")))

    call = wire.ProcCall(
        label="S1",
        proc="TWO",
        symbol_overrides=(wire.SymbolValue(name="HLQ", value=(lit("PROD"),)),),
        parm_overrides=(
            wire.ParmOverride(procstep="", parm=(lit("X"),)),
            wire.ParmOverride(procstep="P2", parm=()),
        ),
        cond_overrides=(
            wire.CondOverride(procstep="P1", cond=wire.Cond(tests=(), mode="NORMAL")),
        ),
        dd_overrides=(
            override_dd("", "FIRST"),
            override_dd("P2", "OUT"),
            override_dd("", "EXTRA"),
        ),
    )

    def written(name: str) -> object:
        return _dd(name, DirectDSN(literal(f"T.{name}")), disp())

    assert job_from_bridge_json(job_json("J", (call,))).steps == (
        ProcCall(
            StepName("S1"),
            ProcRef("TWO"),
            ((SymbolName("HLQ"), literal("PROD")),),
            NotOverridden(),
            literal("X"),
            (written("FIRST"),),
            (
                (
                    StepName("P2"),
                    ProcStepOverrides(parm=(), dds=(written("OUT"), written("EXTRA"))),
                ),
                (
                    StepName("P1"),
                    ProcStepOverrides(cond=StepCondition((), AbendMode.NORMAL)),
                ),
            ),
        ),
    )
