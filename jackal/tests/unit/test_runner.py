import logging
from pathlib import Path

import pytest
from jackal.missing_data import (
    LenientAllocation,
    MissingDataStrategy,
    StrictAllocation,
)
from jackal.missing_program import (
    AbendMissingProgram,
    MissingProgramStrategy,
    StubMissingProgram,
)
from jackal.model import (
    DD,
    AbendMode,
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
    UnresolvedDd,
)
from jackal.results import (
    Abended,
    AfterAbend,
    AfterAllocationFailure,
    AfterJobCond,
    AllocationError,
    AllocationFailed,
    Bypassed,
    BypassReason,
    Completed,
    Flushed,
    JobAbended,
    JobAllocationFailed,
    JobCompleted,
    JobResult,
    SkippedUnresolved,
    StepOutcome,
    SystemAbend,
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


def _run(
    tmp_path: Path,
    j: Job,
    proclib: tuple[Path, ...] = (),
    unresolved: UnresolvedReferenceStrategy = RaiseErrorStrategy(),
    missing_data: MissingDataStrategy = StrictAllocation(),
    missing_program: MissingProgramStrategy = AbendMissingProgram(),
) -> JobResult:
    runner = JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
        unresolved=unresolved,
        missing_data=missing_data,
        missing_program=missing_program,
        proclib_dirs=proclib,
    )
    return runner.run(j, workdir=tmp_path, seeds={})


def _fresh(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir()
    return path


def _outcomes(result: JobResult) -> list[tuple[str, StepOutcome]]:
    return [(s.name, s.outcome) for s in result.steps]


def _back(step: str, ddname: str) -> BackwardRef[StepRef]:
    return BackwardRef(ref(step), UnresolvedDd(DdName(ddname)))


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


def _after_bypassed(tmp_path: Path, name: str, referencing: DD[StepRef]) -> JobResult:
    root = _fresh(tmp_path, name)
    (root / "OLD.FILE").write_bytes(b"")
    j = job(
        "J",
        (
            program("A", "IDCAMS", (_sysin(("DELETE NOPE.NOPE CLUSTER",)),)),
            program(
                "B",
                "IEFBR14",
                (
                    dd("OUT", "MY.FILE", disp("NEW", "CATLG")),
                    dd("WRK", TempRef("TEMP"), disp("NEW", "PASS")),
                    dd("PRIOR", "OLD.FILE"),
                ),
                cond((0, "NE", "")),
            ),
            program("C", "IEFBR14", (referencing,)),
        ),
    )
    return _run(root, j)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_referback_to_a_step_that_did_not_run_allocates_the_name_it_copies(
    tmp_path: Path,
) -> None:
    cases = (
        ("out", dd("IN", _back("B", "OUT"))),
        ("wrk", dd("TMP", _back("B", "WRK"), disp("OLD"))),
        ("prior", dd("IN", _back("B", "PRIOR"))),
    )
    assert [
        _outcomes(_after_bypassed(tmp_path, name, referencing))[1:]
        for name, referencing in cases
    ] == [
        [
            ("B", COND_MET),
            ("C", AllocationFailed(DdName("IN"), AllocationError.DATASET_NOT_FOUND)),
        ],
        [
            ("B", COND_MET),
            ("C", AllocationFailed(DdName("TMP"), AllocationError.TEMP_NOT_CREATED)),
        ],
        [("B", COND_MET), ("C", OK)],
    ]


def _unallocatable() -> Job:
    return job(
        "J",
        (
            program(
                "S1",
                "IEFBR14",
                (
                    _sysin(("CARD",)),
                    dd("OUT", "J.NEW", disp("NEW", "CATLG")),
                    dd("IN", "NO.SUCH"),
                ),
            ),
            program("S2", "IEFBR14"),
        ),
    )


def _files(root: Path) -> list[str]:
    return sorted(p.name for p in root.rglob("*") if p.is_file())


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_strict_allocation_fails_the_step_and_undoes_what_it_allocated(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, _unallocatable())
    failure = AllocationFailed(DdName("IN"), AllocationError.DATASET_NOT_FOUND)
    flushed = Flushed(AfterAllocationFailure(result.steps[0].step))
    assert (_outcomes(result), result.outcome, _files(tmp_path)) == (
        [("S1", failure), ("S2", flushed)],
        JobAllocationFailed(result.steps[0].step, failure),
        [],
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_failed_allocation_flushes_every_later_entry_whatever_it_would_do(
    tmp_path: Path,
) -> None:
    unresolved_referback = BackwardRef(ref("S1"), UnresolvedDd(DdName("BADDD")))
    j = job(
        "J",
        (
            program("S1", "IEFBR14", (dd("IN", "NO.SUCH"),)),
            program("S2", "IEFBR14", condition=cond(mode=AbendMode.EVEN)),
            ProcCall(StepName("S3"), ProcRef("NOSUCHP")),
            program("S4", "IEFBR14", (dd("IN", unresolved_referback),)),
        ),
    )
    result = _run(tmp_path, j, unresolved=IgnoreStrategy())
    flushed = Flushed(AfterAllocationFailure(result.steps[0].step))
    assert _outcomes(result) == [
        ("S1", AllocationFailed(DdName("IN"), AllocationError.DATASET_NOT_FOUND)),
        ("S2", flushed),
        ("S3", flushed),
        ("S4", flushed),
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_lenient_allocation_runs_the_step_on_an_empty_dataset_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="jackal.missing_data"):
        result = _run(tmp_path, _unallocatable(), missing_data=LenientAllocation())
    assert (_outcomes(result), result.outcome, caplog.messages) == (
        [("S1", OK), ("S2", OK)],
        JobCompleted(0),
        ["S1 DD IN: DATASET_NOT_FOUND; allocated an empty dataset in its place"],
    )


def _missing_program() -> Job:
    return job(
        "J",
        (
            program(
                "S1",
                "SORT",
                (
                    dd("KEPT", "J.KEPT", disp("NEW", "CATLG", "CATLG")),
                    dd("GONE", "J.GONE", disp("NEW", "CATLG", "DELETE")),
                ),
            ),
            program("S2", "IEFBR14"),
            program("S3", "IEFBR14", condition=cond(mode=AbendMode.EVEN)),
            program("S4", "IEFBR14", condition=cond(mode=AbendMode.ONLY)),
        ),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_missing_program_abends_s806_and_its_datasets_take_their_abnormal_disp(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, _missing_program())
    s1, s806 = result.steps[0].step, SystemAbend(0x806)
    assert (_outcomes(result), result.outcome, _files(tmp_path)) == (
        [
            ("S1", Abended(s806)),
            ("S2", Flushed(AfterAbend(s1))),
            ("S3", OK),
            ("S4", OK),
        ],
        JobAbended(s1, s806),
        ["J_KEPT"],
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_stubbed_missing_program_completes_with_rc_0_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="jackal.missing_program"):
        result = _run(
            tmp_path, _missing_program(), missing_program=StubMissingProgram()
        )
    assert (_outcomes(result), result.outcome, caplog.messages, _files(tmp_path)) == (
        [
            ("S1", OK),
            ("S2", OK),
            ("S3", OK),
            ("S4", Bypassed(BypassReason.ONLY_WITHOUT_ABEND)),
        ],
        JobCompleted(0),
        ["S1: no program SORT; stubbed with RC 0"],
        ["J_GONE", "J_KEPT"],
    )


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
