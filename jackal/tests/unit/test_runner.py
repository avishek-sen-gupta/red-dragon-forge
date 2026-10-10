from pathlib import Path

import pytest
from jackal.model import (
    UnresolvedDd,
    DD,
    BackwardRef,
    CondOp,
    DdName,
    IfBlock,
    InStreamDSN,
    Job,
    NoDSN,
    ProcCall,
    ProcRef,
    RcTest,
    StepName,
    StepRef,
    TempRef,
)
from jackal.results import (
    AfterJobCond,
    BypassReason,
    Bypassed,
    Completed,
    Flushed,
    JobResult,
    SkippedUnresolved,
    StepOutcome,
)
from jackal.runner import JobRunner, UnsupportedStep
from jackal.unresolved import (
    IgnoreStrategy,
    RaiseErrorStrategy,
    UnresolvedReference,
    UnresolvedReferenceStrategy,
)
from tests.covers import NotLanguageFeature, covers
from tests.model_build import cond, dd, disp, job, program, ref

OK = Completed(0)
COND_MET = Bypassed(BypassReason.COND_SATISFIED)
NOT_RUN = Bypassed(BypassReason.REFERENCED_STEP_NOT_RUN)


def _run(
    tmp_path: Path,
    j: Job,
    proclib: tuple[Path, ...] = (),
    unresolved: UnresolvedReferenceStrategy = RaiseErrorStrategy(),
) -> JobResult:
    runner = JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
        unresolved=unresolved,
        proclib_dirs=proclib,
    )
    return runner.run(j, workdir=tmp_path, seeds={})


def _fresh(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir()
    return path


def _outcomes(result: JobResult) -> list[tuple[str, StepOutcome]]:
    return [(s.name, s.outcome) for s in result.steps]


def _sysin(lines: tuple[str, ...]) -> DD[StepRef]:
    return DD(DdName("SYSIN"), InStreamDSN(), disp(), in_stream=lines)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_runner_runs_every_step_in_order(tmp_path: Path) -> None:
    j = job(
        "J",
        (
            program("A", "IEFBR14", (dd("D", "J.X", disp("NEW", "DELETE", "DELETE")),)),
            program("B", "IEFBR14"),
        ),
    )
    assert _outcomes(_run(tmp_path, j)) == [("A", OK), ("B", OK)]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_runner_idcams_creates_ksds(tmp_path: Path) -> None:
    sysin = (
        "DELETE MYAPP.ACCOUNTS CLUSTER",
        "IF MAXCC LE 8 THEN SET MAXCC = 0",
        "DEFINE CLUSTER ( -",
        "  NAME(MYAPP.ACCOUNTS) -",
        "  RECORDSIZE(300 300) -",
        "  KEYS(10 0) -",
        ") DATA ( -",
        "  NAME(MYAPP.ACCOUNTS.DATA) -",
        ")",
    )
    sysprint = DD(DdName("SYSPRINT"), NoDSN(), disp(), sysout=True)
    j = job("DEFTEST", (program("DEFACCT", "IDCAMS", (_sysin(sysin), sysprint)),))
    assert _outcomes(_run(tmp_path, j)) == [("DEFACCT", OK)]
    assert (tmp_path / "MYAPP_ACCOUNTS").exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_step_and_job_cond_bypass_after_a_failure_and_not_after_success(
    tmp_path: Path,
) -> None:
    fails = program("A", "IDCAMS", (_sysin(("DELETE NOPE.NOPE CLUSTER",)),))
    guarded = program("B", "IEFBR14", condition=cond((0, "NE", "")))
    clean = job("J", (program("A", "IEFBR14"), guarded))
    after_failure = job("J", (fails, guarded))
    job_cond = job("J", (fails, program("B", "IEFBR14")), end_job_tests=((0, "NE"),))
    flushed = _run(_fresh(tmp_path, "job"), job_cond)
    assert [
        _outcomes(_run(_fresh(tmp_path, "clean"), clean)),
        _outcomes(_run(_fresh(tmp_path, "failure"), after_failure)),
        _outcomes(flushed),
    ] == [
        [("A", OK), ("B", OK)],
        [("A", Completed(8)), ("B", COND_MET)],
        [("A", Completed(8)), ("B", Flushed(AfterJobCond(flushed.steps[0].step)))],
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_referback_names_the_earlier_steps_dataset_or_temporary(
    tmp_path: Path,
) -> None:
    j = job(
        "J",
        (
            program(
                "S1",
                "IEFBR14",
                (
                    dd("OUT", "MY.FILE", disp("NEW", "CATLG")),
                    dd("WRK", TempRef("TEMP"), disp("NEW", "PASS")),
                ),
            ),
            program(
                "S2",
                "IEFBR14",
                (
                    dd(
                        "IN",
                        BackwardRef(ref("S1"), UnresolvedDd(DdName("OUT"))),
                        disp("OLD"),
                    ),
                    dd(
                        "TMP",
                        BackwardRef(ref("S1"), UnresolvedDd(DdName("WRK"))),
                        disp("OLD"),
                    ),
                ),
            ),
        ),
    )
    assert _outcomes(_run(tmp_path, j)) == [("S1", OK), ("S2", OK)]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_referback_to_a_bypassed_step_bypasses_its_step(tmp_path: Path) -> None:
    j = job(
        "J",
        (
            program("A", "IDCAMS", (_sysin(("DELETE NOPE.NOPE CLUSTER",)),)),
            program(
                "B",
                "IEFBR14",
                (dd("OUT", "MY.FILE", disp("NEW", "CATLG")),),
                cond((0, "NE", "")),
            ),
            program(
                "C",
                "IEFBR14",
                (dd("IN", BackwardRef(ref("B"), UnresolvedDd(DdName("OUT")))),),
            ),
        ),
    )
    assert _outcomes(_run(tmp_path, j)) == [
        ("A", Completed(8)),
        ("B", COND_MET),
        ("C", NOT_RUN),
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_raise_strategy_rejects_an_unresolved_reference_before_any_step_runs(
    tmp_path: Path,
) -> None:
    first = program("S1", "NOSOURCE")
    referback = job(
        "J",
        (
            first,
            program(
                "S2",
                "IEFBR14",
                (dd("IN", BackwardRef(ref("S1"), UnresolvedDd(DdName("BADDD")))),),
            ),
        ),
    )
    test = job(
        "J", (first, program("S2", "IEFBR14", condition=cond((4, "LT", "NOPE"))))
    )
    call = job("J", (first, ProcCall(StepName("S2"), ProcRef("NOSUCHP"))))
    messages = (
        "S2 refers to a step or DD that is not resolved (blueprint D7)",
        "S2 refers to a step or DD that is not resolved (blueprint D7)",
        "S2: PROC NOSUCHP is in no proclib (blueprint D7)",
    )
    for j, message in zip((referback, test, call), messages):
        with pytest.raises(UnresolvedReference) as raised:
            _run(tmp_path, j)
        assert str(raised.value) == message


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_ignore_strategy_drops_unresolved_tests_and_skips_what_cannot_run(
    tmp_path: Path,
) -> None:
    j = job(
        "J",
        (
            program("S1", "IEFBR14", (dd("WRK", "MY.FILE", disp("NEW", "CATLG")),)),
            program("S2", "IEFBR14", condition=cond((4, "LT", "NOPE"))),
            program(
                "S3",
                "IEFBR14",
                (dd("IN", BackwardRef(ref("S1"), UnresolvedDd(DdName("BADDD")))),),
            ),
            ProcCall(StepName("S4"), ProcRef("NOSUCHP")),
            program("S5", "IEFBR14", condition=cond((0, "EQ", "S3"))),
        ),
    )
    assert _outcomes(_run(tmp_path, j, unresolved=IgnoreStrategy())) == [
        ("S1", OK),
        ("S2", OK),
        ("S3", SkippedUnresolved()),
        ("S4", SkippedUnresolved()),
        ("S5", OK),
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_the_runner_allocates_before_and_disposes_after_every_program(
    tmp_path: Path,
) -> None:
    sysout = DD(DdName("SYSPRINT"), NoDSN(), disp(), sysout=True)
    kept = dd("K", "J.KEEP", disp("NEW", "CATLG"))
    j = job(
        "J",
        (
            program(
                "S1", "IEFBR14", (dd("D", "J.TMP", disp("NEW", "DELETE")), kept, sysout)
            ),
        ),
    )
    assert (
        _outcomes(_run(tmp_path, j)),
        sorted(p.name for p in tmp_path.rglob("*") if p.is_file()),
    ) == ([("S1", OK)], ["J_KEEP"])


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_the_runner_applies_disp_to_an_idcams_steps_dds(tmp_path: Path) -> None:
    j = job(
        "J",
        (
            program("S1", "IEFBR14", (dd("OLDF", "MY.FILE", disp("NEW", "CATLG")),)),
            program(
                "S2",
                "IDCAMS",
                (
                    _sysin(("DELETE NOPE.NOPE CLUSTER",)),
                    dd("OLDF", "MY.FILE", disp("OLD", "DELETE")),
                ),
            ),
        ),
    )
    assert (
        _outcomes(_run(tmp_path, j)),
        (tmp_path / "MY_FILE").exists(),
    ) == ([("S1", OK), ("S2", Completed(8))], False)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_runner_expands_a_proc_call_before_running(tmp_path: Path) -> None:
    (tmp_path / "proc").mkdir()
    (tmp_path / "proc" / "WRAPIT.prc").write_text(
        "//WRAPIT PROC\n"
        "//P1 EXEC PGM=IEFBR14\n"
        "//D DD DSN=J.X,DISP=(NEW,DELETE,DELETE)\n"
        "// PEND\n"
    )
    j = job("J", (ProcCall(StepName("STEP1"), ProcRef("WRAPIT")),))
    assert _outcomes(_run(tmp_path, j, (tmp_path / "proc",))) == [("STEP1.P1", OK)]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_runner_refuses_a_step_under_an_if(tmp_path: Path) -> None:
    guarded = job(
        "J",
        (
            program("S1", "IEFBR14"),
            IfBlock(
                StepName("C1"),
                RcTest(ref("S1"), CondOp.EQ, 0),
                (program("S2", "IEFBR14"),),
            ),
        ),
    )
    with pytest.raises(UnsupportedStep, match="S2 is under an IF"):
        _run(tmp_path, guarded)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_concatenated_dd_is_refused_rather_than_read_as_its_first_dataset(
    tmp_path: Path,
) -> None:
    from jackal.model import ConcatMember, DirectDSN
    from jackal.value_parts import literal

    member = ConcatMember(DirectDSN(literal("T.B")), disp("SHR"))
    concatenated = DD(
        DdName("IN"), DirectDSN(literal("T.A")), disp("SHR"), concatenated=(member,)
    )
    steplib = DD(
        DdName("STEPLIB"),
        DirectDSN(literal("T.L")),
        disp("NEW"),
        concatenated=(member,),
    )
    refused = job("J", (program("S1", "IEFBR14", (concatenated,)),))
    library_only = job("J", (program("S1", "IEFBR14", (steplib,)),))
    with pytest.raises(UnsupportedStep, match="S1 concatenates DD IN"):
        _run(tmp_path, refused)
    assert _outcomes(_run(_fresh(tmp_path, "lib"), library_only)) == [("S1", OK)]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_referback_to_a_dummy_dd_names_dummy(tmp_path: Path) -> None:
    from jackal.model import DummyDSN

    j = job(
        "J",
        (
            program("S1", "IEFBR14", (DD(DdName("A"), DummyDSN(), disp()),)),
            program(
                "S2",
                "IEFBR14",
                (dd("B", BackwardRef(ref("S1"), UnresolvedDd(DdName("A")))),),
            ),
        ),
    )
    assert _outcomes(_run(tmp_path, j)) == [("S1", OK), ("S2", OK)]
