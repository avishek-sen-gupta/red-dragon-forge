import logging
from pathlib import Path

import pytest
from catnip.labels import KsdsLabel, LabelPending, RecordFormat, SequentialLabel
from catnip.system_catalog import CATALOG_FILE, NotCataloged, SystemCatalog
from infrastructure.zos.abend.system_abend import SystemAbend
from infrastructure.zos.abend.user_abend import UserAbend
from interpreter.vm.builtins import core_builtins
from jackal.catalog import Dataset
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
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
    AbendCodeTest,
    AbendMode,
    AbendTest,
    AllOf,
    AllPriorSteps,
    AnyOf,
    BackwardRef,
    CondOp,
    DdName,
    IfBlock,
    InStreamDSN,
    Job,
    Negated,
    NoDSN,
    ProcCall,
    ProcRef,
    ProgramStep,
    RcTest,
    RunTest,
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
)
from jackal.runner import JobRunner
from jackal.unknown_return_code import RaiseUnknownReturnCode
from jackal.unresolved import (
    IgnoreStrategy,
    RaiseErrorStrategy,
    UnresolvedReference,
    UnresolvedReferenceStrategy,
)
from tests.covers import NotLanguageFeature, covers
from tests.model_build import cond, dd, disp, job, program, ref
from tests.package_build import EMPTY

OK = Completed(0)
FB80 = SequentialLabel(RecordFormat.FB, 80)
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
        package=EMPTY,
        system=SystemCatalog(tmp_path / "system"),
        unresolved=unresolved,
        missing_data=missing_data,
        missing_program=missing_program,
        unknown_return_code=RaiseUnknownReturnCode(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        proclib_dirs=proclib,
        builtins=core_builtins(),
    )
    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    return runner.run(j, scratch=scratch)


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
        " DELETE MYAPP.ACCOUNTS CLUSTER",
        " IF MAXCC LE 8 THEN SET MAXCC = 0",
        " DEFINE CLUSTER ( -",
        "   NAME(MYAPP.ACCOUNTS) -",
        "   RECORDSIZE(300 300) -",
        "   KEYS(10 0) -",
        " ) DATA ( -",
        "   NAME(MYAPP.ACCOUNTS.DATA) -",
        " )",
    )
    sysprint = DD(DdName("SYSPRINT"), NoDSN(), disp(), sysout=True)
    j = job("DEFTEST", (program("DEFACCT", "IDCAMS", (_sysin(sysin), sysprint)),))
    assert (_outcomes(_run(tmp_path, j)), _cataloged(tmp_path, "MYAPP.ACCOUNTS")) == (
        [("DEFACCT", OK)],
        Dataset(
            "MYAPP.ACCOUNTS",
            tmp_path / "system" / "datasets" / "MYAPP.ACCOUNTS",
            KsdsLabel(300, 0, 10),
        ),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_step_and_job_cond_bypass_after_a_failure_and_not_after_success(
    tmp_path: Path,
) -> None:
    fails = program("A", "IDCAMS", (_sysin((" DELETE NOPE.NOPE CLUSTER",)),))
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
    _uploaded(root, "OLD.FILE", b"")
    j = job(
        "J",
        (
            program("A", "IDCAMS", (_sysin((" DELETE NOPE.NOPE CLUSTER",)),)),
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
    return sorted(
        p.name for p in root.rglob("*") if p.is_file() and p.name != CATALOG_FILE
    )


def _cataloged(root: Path, dsn: str) -> Dataset | NotCataloged:
    return SystemCatalog(root / "system").lookup(dsn)


def _uploaded(root: Path, dsn: str, data: bytes) -> None:
    upload = root / f"{dsn}.upload"
    upload.write_bytes(data)
    SystemCatalog(root / "system").add(dsn, upload, FB80)
    upload.unlink()


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
        ["J.KEPT"],
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
        ["J.GONE", "J.KEPT"],
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_dataset_the_job_creates_and_passes_but_never_receives_is_deleted_at_job_end(
    tmp_path: Path,
) -> None:
    _uploaded(tmp_path, "J.OLD", b"x" * 80)
    j = job(
        "J",
        (
            program(
                "S1",
                "IEFBR14",
                (
                    dd("A", "J.UNRCVD", disp("NEW", "PASS")),
                    dd("B", "J.KEPT", disp("NEW", "PASS")),
                    dd("C", "J.REPASS", disp("NEW", "PASS")),
                    dd("D", "J.OLD", disp("OLD", "PASS")),
                ),
            ),
            program(
                "S2",
                "IEFBR14",
                (
                    dd("B", "J.KEPT", disp("OLD", "CATLG")),
                    dd("C", "J.REPASS", disp("OLD", "PASS")),
                ),
            ),
        ),
    )
    result = _run(tmp_path, j)
    assert (_outcomes(result), _files(tmp_path)) == (
        [("S1", OK), ("S2", OK)],
        ["J.KEPT", "J.OLD"],
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_what_one_job_catalogs_or_deletes_is_what_the_next_job_sees(
    tmp_path: Path,
) -> None:
    upload = tmp_path / "gone.dat"
    upload.write_bytes(b"x" * 80)
    SystemCatalog(tmp_path / "system").add(
        "J.GONE", upload, SequentialLabel(RecordFormat.FB, 80)
    )
    first = job(
        "J1",
        (
            program(
                "S1",
                "IEFBR14",
                (
                    dd("O", "J.OUT", disp("NEW", "CATLG")),
                    dd("G", "J.GONE", disp("OLD", "DELETE")),
                ),
            ),
        ),
    )
    second = job(
        "J2",
        (
            program("S1", "IEFBR14", (dd("O", "J.OUT", disp("SHR")),)),
            program("S2", "IEFBR14", (dd("G", "J.GONE", disp("SHR")),)),
        ),
    )
    first_result, second_result = _run(tmp_path, first), _run(tmp_path, second)
    system = SystemCatalog(tmp_path / "system")
    assert (
        _outcomes(first_result),
        _outcomes(second_result),
        system.lookup("J.OUT"),
        system.lookup("J.GONE"),
    ) == (
        [("S1", OK)],
        [
            ("S1", OK),
            ("S2", AllocationFailed(DdName("G"), AllocationError.DATASET_NOT_FOUND)),
        ],
        Dataset("J.OUT", tmp_path / "system" / "datasets" / "J.OUT", LabelPending()),
        NotCataloged(),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_mod_with_no_normal_disposition_deletes_a_dataset_it_created_and_keeps_one_it_found(
    tmp_path: Path,
) -> None:
    _uploaded(tmp_path, "J.FOUND", b"x" * 80)
    j = job(
        "J",
        (
            program(
                "S1",
                "IEFBR14",
                (
                    dd("A", "J.CREATED", disp("MOD")),
                    dd("B", "J.FOUND", disp("MOD")),
                    dd("C", "J.CATLGD", disp("MOD", "CATLG")),
                    dd("D", "J.MODPASS", disp("MOD", "PASS")),
                ),
            ),
        ),
    )
    assert (
        _outcomes(_run(tmp_path, j)),
        _cataloged(tmp_path, "J.CREATED"),
        _files(tmp_path / "system"),
    ) == ([("S1", OK)], NotCataloged(), ["J.CATLGD", "J.FOUND"])


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
        _files(tmp_path),
    ) == ([("S1", OK)], ["J.KEEP"])


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
                    _sysin((" DELETE NOPE.NOPE CLUSTER",)),
                    dd("OLDF", "MY.FILE", disp("OLD", "DELETE")),
                ),
            ),
        ),
    )
    assert (
        _outcomes(_run(tmp_path, j)),
        _cataloged(tmp_path, "MY.FILE"),
    ) == ([("S1", OK), ("S2", Completed(8))], NotCataloged())


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


IF_FALSE = Bypassed(BypassReason.IF_CONDITION_FALSE)
RC8 = Completed(8)


def _rc8(label: str) -> ProgramStep[StepRef]:
    return program(label, "IDCAMS", (_sysin((" DELETE NO.SUCH.DATASET",)),))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_an_if_construct_runs_the_branch_its_return_code_tests_choose(
    tmp_path: Path,
) -> None:
    """z/OS 3.1 JCL Reference, ch. 18: RC is the highest return code of the steps
    that ran; a test of a step that did not start is false, negated or not."""
    j = job(
        "J",
        (
            program("S1", "IEFBR14"),
            _rc8("S2"),
            IfBlock(
                StepName("T1"),
                RcTest(AllPriorSteps(), CondOp.GT, 4),
                (
                    program("THEN1", "IEFBR14"),
                    IfBlock(
                        StepName("T2"),
                        RcTest(ref("S1"), CondOp.EQ, 0),
                        (program("NESTED", "IEFBR14"),),
                    ),
                ),
                (program("ELSE1", "IEFBR14"),),
            ),
            IfBlock(
                StepName("T3"),
                AnyOf(
                    (
                        RcTest(ref("ELSE1"), CondOp.EQ, 0),
                        Negated(RcTest(ref("ELSE1"), CondOp.EQ, 0)),
                    )
                ),
                (program("NOTRUN", "IEFBR14"),),
            ),
            IfBlock(
                StepName("T4"),
                AllOf((Negated(RunTest(ref("ELSE1"))), RunTest(ref("S2")))),
                (program("RUNTEST", "IEFBR14"),),
            ),
        ),
    )
    assert _outcomes(_run(tmp_path, j)) == [
        ("S1", OK),
        ("S2", RC8),
        ("THEN1", OK),
        ("NESTED", OK),
        ("ELSE1", IF_FALSE),
        ("NOTRUN", IF_FALSE),
        ("RUNTEST", OK),
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_after_an_abend_only_steps_whose_if_tests_an_abend_run(
    tmp_path: Path,
) -> None:
    """z/OS 3.1 JCL Reference, ch. 18, Defaults: after an abend, steps in an IF
    construct run only when it tests ABEND, ABENDCC or ¬ABEND; the IF and the
    step's own COND must both allow it."""
    s806 = SystemAbend(0x806)
    j = job(
        "J",
        (
            program("S1", "NOSUCHPG"),
            IfBlock(
                StepName("T4"),
                AllOf(
                    (AbendTest(AllPriorSteps()), RcTest(AllPriorSteps(), CondOp.EQ, 0))
                ),
                (program("RCZERO", "IEFBR14"),),
            ),
            IfBlock(
                StepName("T1"),
                RcTest(AllPriorSteps(), CondOp.EQ, 0),
                (program("RCONLY", "IEFBR14"),),
            ),
            IfBlock(
                StepName("T2"),
                AbendTest(AllPriorSteps()),
                (
                    program("ONABEND", "IEFBR14"),
                    program("CONDBYP", "IEFBR14", condition=cond((0, "EQ", ""))),
                ),
                (program("NOABEND", "IEFBR14"),),
            ),
            IfBlock(
                StepName("T3"),
                AllOf(
                    (
                        AbendCodeTest(ref("S1"), SystemAbend(0x806)),
                        Negated(AbendCodeTest(AllPriorSteps(), UserAbend(100))),
                    )
                ),
                (program("CC806", "IEFBR14"),),
            ),
            program("AFTER", "IEFBR14"),
        ),
    )
    result = _run(tmp_path, j)
    flushed = Flushed(AfterAbend(result.steps[0].step))
    assert _outcomes(result) == [
        ("S1", Abended(s806)),
        ("RCZERO", OK),
        ("RCONLY", flushed),
        ("ONABEND", OK),
        ("CONDBYP", COND_MET),
        ("NOABEND", IF_FALSE),
        ("CC806", OK),
        ("AFTER", flushed),
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_concatenation_fails_allocation_at_a_missing_member_and_undoes_the_rest(
    tmp_path: Path,
) -> None:
    from jackal.model import ConcatMember, DirectDSN
    from jackal.value_parts import literal

    missing = ConcatMember(DirectDSN(literal("T.GONE")), disp("SHR"))
    concatenated = DD(
        DdName("IN"),
        DirectDSN(literal("T.NEW")),
        disp("NEW", "CATLG", "DELETE"),
        concatenated=(missing,),
    )
    steplib = DD(
        DdName("STEPLIB"),
        DirectDSN(literal("T.L")),
        disp("NEW"),
        concatenated=(missing,),
    )
    failed = job("J", (program("S1", "IEFBR14", (concatenated,)),))
    library_only = job("J", (program("S1", "IEFBR14", (steplib,)),))
    assert (
        _outcomes(_run(tmp_path, failed)),
        _cataloged(tmp_path, "T.NEW"),
        _files(tmp_path / "system"),
        _outcomes(_run(_fresh(tmp_path, "lib"), library_only)),
    ) == (
        [("S1", AllocationFailed(DdName("IN"), AllocationError.DATASET_NOT_FOUND))],
        NotCataloged(),
        [],
        [("S1", OK)],
    )


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
