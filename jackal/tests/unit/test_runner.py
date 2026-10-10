from pathlib import Path

import pytest

from tests.covers import NotLanguageFeature, covers
from tests.model_build import cond, dd, disp, job, program, ref
from jackal.dsn import BackwardRef, DdName, InStreamDSN, NoDSN, TempRef
from jackal.expansion import DanglingDdReference, ExpansionFailed
from jackal.model import (
    DD,
    IfBlock,
    Job,
    ProcCall,
    ProcRef,
    RcTest,
    CondOp,
    StepName,
    StepRef,
)
from jackal.results import JobResult, StepDisposition
from jackal.runner import JobRunner, UnsupportedStep

EXECUTED, BYPASSED = StepDisposition.EXECUTED, StepDisposition.BYPASSED


def _run(tmp_path: Path, j: Job, proclib: tuple[Path, ...] = ()) -> JobResult:
    runner = JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
        proclib_dirs=proclib,
    )
    return runner.run(j, workdir=tmp_path, seeds={})


def _fresh(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir()
    return path


def _outcomes(result: JobResult) -> list[tuple[str, int, StepDisposition]]:
    return [(s.name, s.return_code, s.disposition) for s in result.steps]


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
    assert _outcomes(_run(tmp_path, j)) == [("A", 0, EXECUTED), ("B", 0, EXECUTED)]


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
    assert _outcomes(_run(tmp_path, j)) == [("DEFACCT", 0, EXECUTED)]
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
    assert [
        _outcomes(_run(_fresh(tmp_path, "clean"), clean)),
        _outcomes(_run(_fresh(tmp_path, "failure"), after_failure)),
        _outcomes(_run(_fresh(tmp_path, "job"), job_cond)),
    ] == [
        [("A", 0, EXECUTED), ("B", 0, EXECUTED)],
        [("A", 8, EXECUTED), ("B", 0, BYPASSED)],
        [("A", 8, EXECUTED), ("B", 0, BYPASSED)],
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
                    dd("IN", BackwardRef(ref("S1"), DdName("OUT")), disp("OLD")),
                    dd("TMP", BackwardRef(ref("S1"), DdName("WRK")), disp("OLD")),
                ),
            ),
        ),
    )
    assert _outcomes(_run(tmp_path, j)) == [("S1", 0, EXECUTED), ("S2", 0, EXECUTED)]


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
            program("C", "IEFBR14", (dd("IN", BackwardRef(ref("B"), DdName("OUT"))),)),
        ),
    )
    assert _outcomes(_run(tmp_path, j)) == [
        ("A", 8, EXECUTED),
        ("B", 0, BYPASSED),
        ("C", 0, BYPASSED),
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_referback_to_a_dd_the_step_lacks_fails_before_anything_runs(
    tmp_path: Path,
) -> None:
    j = job(
        "J",
        (
            program("S1", "IEFBR14", (dd("WRK", "MY.FILE", disp("NEW", "CATLG")),)),
            program(
                "S2", "IEFBR14", (dd("IN", BackwardRef(ref("S1"), DdName("BADDD"))),)
            ),
        ),
    )
    with pytest.raises(ExpansionFailed) as failure:
        _run(tmp_path, j)
    assert isinstance(failure.value.error, DanglingDdReference)
    assert failure.value.error.ddname == DdName("BADDD")


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
    assert _outcomes(_run(tmp_path, j, (tmp_path / "proc",))) == [
        ("STEP1.P1", 0, EXECUTED)
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_runner_refuses_an_unresolved_proc_and_a_step_under_an_if(
    tmp_path: Path,
) -> None:
    unresolved = job("J", (ProcCall(StepName("S1"), ProcRef("NOSUCHP")),))
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
    with pytest.raises(UnsupportedStep, match="PROC NOSUCHP is in no proclib"):
        _run(tmp_path, unresolved)
    with pytest.raises(UnsupportedStep, match="S2 is under an IF"):
        _run(tmp_path, guarded)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_concatenated_dd_is_refused_rather_than_read_as_its_first_dataset(
    tmp_path: Path,
) -> None:
    from jackal.dsn import DirectDSN
    from jackal.model import ConcatMember
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
    assert _outcomes(_run(_fresh(tmp_path, "lib"), library_only)) == [
        ("S1", 0, EXECUTED)
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_referback_to_a_dummy_dd_names_dummy(tmp_path: Path) -> None:
    from jackal.dsn import DummyDSN

    j = job(
        "J",
        (
            program("S1", "IEFBR14", (DD(DdName("A"), DummyDSN(), disp()),)),
            program("S2", "IEFBR14", (dd("B", BackwardRef(ref("S1"), DdName("A"))),)),
        ),
    )
    assert _outcomes(_run(tmp_path, j)) == [("S1", 0, EXECUTED), ("S2", 0, EXECUTED)]
