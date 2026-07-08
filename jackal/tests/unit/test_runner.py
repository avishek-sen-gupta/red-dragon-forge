from pathlib import Path

from tests.covers import NotLanguageFeature, covers

from jackal.dsn import DirectDSN
from jackal.model import DD, Cond, CondOp, Disp, DispNormal, DispStatus, Job, Step
from jackal.results import StepDisposition
from jackal.runner import JobRunner
from jackal.value_parts import literal

_DUMMY_DISP = Disp(DispStatus.NEW, DispNormal.DELETE, DispNormal.DELETE)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_runner_runs_all_steps(tmp_path: Path) -> None:
    job = Job(
        name="J",
        steps=(
            Step(
                name="A",
                pgm="IEFBR14",
                dds=(
                    DD(
                        "D",
                        DirectDSN(literal("J.X")),
                        Disp(DispStatus.NEW, DispNormal.DELETE, DispNormal.DELETE),
                    ),
                ),
            ),
            Step(name="B", pgm="IEFBR14", dds=()),
        ),
    )
    runner = JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )
    res = runner.run(job, workdir=tmp_path, seeds={})
    assert [s.name for s in res.steps] == ["A", "B"]
    assert all(s.ran and s.return_code == 0 for s in res.steps)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_runner_idcams_creates_ksds(tmp_path: Path) -> None:
    """An IDCAMS-only job (in-stream DELETE+DEFINE) creates a KSDS in the catalog."""
    sysin_lines = (
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
    step = Step(
        name="DEFACCT",
        pgm="IDCAMS",
        dds=(
            DD(
                ddname="SYSIN",
                dsn=DirectDSN(()),
                disp=_DUMMY_DISP,
                in_stream=sysin_lines,
            ),
            DD(
                ddname="SYSPRINT",
                dsn=DirectDSN(()),
                disp=_DUMMY_DISP,
                sysout=True,
            ),
        ),
    )
    job = Job(name="DEFTEST", steps=(step,))
    runner = JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )
    res = runner.run(job, workdir=tmp_path, seeds={})
    assert res.steps[0].return_code == 0
    assert res.steps[0].ran is True
    assert (tmp_path / "MYAPP_ACCOUNTS").exists()


def _idcams_delete_missing(name: str, conds: tuple[Cond, ...] = ()) -> Step:
    # DELETE of an uncataloged DSN -> MAXCC 8 (real nonzero RC, no COBOL/bridge).
    return Step(
        name=name,
        pgm="IDCAMS",
        dds=(
            DD(
                ddname="SYSIN",
                dsn=DirectDSN(()),
                disp=_DUMMY_DISP,
                in_stream=("DELETE NOPE.NOPE CLUSTER",),
            ),
        ),
        conds=conds,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cond_bypasses_step_after_failure(tmp_path: Path) -> None:
    job = Job(
        name="J",
        steps=(
            _idcams_delete_missing("A"),  # MAXCC 8
            Step(
                name="B",
                pgm="IEFBR14",
                dds=(),
                conds=(Cond(code=0, op=CondOp.NE),),  # bypass if any prior rc != 0
            ),
        ),
    )
    runner = JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )
    res = runner.run(job, workdir=tmp_path, seeds={})
    a, b = res.steps
    assert a.return_code == 8 and a.disposition is StepDisposition.EXECUTED
    assert b.disposition is StepDisposition.BYPASSED and b.ran is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cond_runs_step_when_clean(tmp_path: Path) -> None:
    job = Job(
        name="J",
        steps=(
            Step(name="A", pgm="IEFBR14", dds=()),  # RC 0
            Step(
                name="B",
                pgm="IEFBR14",
                dds=(),
                conds=(Cond(code=0, op=CondOp.NE),),
            ),
        ),
    )
    runner = JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )
    res = runner.run(job, workdir=tmp_path, seeds={})
    assert all(s.disposition is StepDisposition.EXECUTED for s in res.steps)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_job_level_cond_applies_to_all_steps(tmp_path: Path) -> None:
    job = Job(
        name="J",
        steps=(
            _idcams_delete_missing("A"),  # MAXCC 8
            Step(name="B", pgm="IEFBR14", dds=()),  # no own COND
        ),
        cond=(Cond(code=0, op=CondOp.NE),),  # job-level: bypass all after a failure
    )
    runner = JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )
    res = runner.run(job, workdir=tmp_path, seeds={})
    assert res.steps[1].disposition is StepDisposition.BYPASSED


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_resolve_step_substitutes_backref(tmp_path: Path) -> None:
    from jackal.dsn import BackwardRef, DirectDSN
    from jackal.model import DD, Disp, DispNormal, DispStatus, Step

    runner = JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )
    resolved_dds = {"STEP1": {"WRK": DirectDSN(literal("MY.FILE"))}}
    step = Step(
        name="STEP2",
        pgm="IEFBR14",
        dds=(
            DD(
                "INPUT",
                BackwardRef("STEP1", "WRK"),
                Disp(DispStatus.OLD, DispNormal.DELETE, DispNormal.DELETE),
            ),
        ),
    )
    result = runner._resolve_step(step, resolved_dds)
    assert result is not None
    assert result.dds[0].dsn == DirectDSN(literal("MY.FILE"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_resolve_step_returns_none_when_referenced_step_absent(tmp_path: Path) -> None:
    from jackal.dsn import BackwardRef
    from jackal.model import DD, Disp, DispNormal, DispStatus, Step

    runner = JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )
    step = Step(
        name="STEP2",
        pgm="IEFBR14",
        dds=(
            DD(
                "INPUT",
                BackwardRef("MISSING", "WRK"),
                Disp(DispStatus.OLD, DispNormal.DELETE, DispNormal.DELETE),
            ),
        ),
    )
    assert runner._resolve_step(step, resolved_dds={}) is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_record_dds_stores_temp_ref_as_direct_dsn(tmp_path: Path) -> None:
    from jackal.dsn import DirectDSN, TempRef
    from jackal.model import DD, Disp, DispNormal, DispStatus

    runner = JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )
    dds = (
        DD(
            "WRK",
            TempRef("&&TEMP"),
            Disp(DispStatus.NEW, DispNormal.PASS, DispNormal.DELETE),
        ),
        DD(
            "OUT",
            DirectDSN(literal("MY.FILE")),
            Disp(DispStatus.NEW, DispNormal.KEEP, DispNormal.DELETE),
        ),
    )
    registry: dict = {}
    runner._record_dds("STEP1", dds, registry)
    assert registry["STEP1"]["WRK"] == DirectDSN(literal("TEMP"))  # alias[2:]
    assert registry["STEP1"]["OUT"] == DirectDSN(literal("MY.FILE"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_resolve_step_raises_for_unknown_ddname(tmp_path: Path) -> None:
    from jackal.dsn import BackwardRef, DirectDSN
    from jackal.model import DD, Disp, DispNormal, DispStatus, Step
    import pytest

    runner = JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )
    resolved_dds = {"STEP1": {"WRK": DirectDSN(literal("MY.FILE"))}}
    step = Step(
        name="STEP2",
        pgm="IEFBR14",
        dds=(
            DD(
                "INPUT",
                BackwardRef("STEP1", "BADDD"),
                Disp(DispStatus.OLD, DispNormal.DELETE, DispNormal.DELETE),
            ),
        ),
    )
    with pytest.raises(KeyError, match="BADDD"):
        runner._resolve_step(step, resolved_dds)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_runner_expands_proc_call_before_running(tmp_path: Path) -> None:
    (tmp_path / "proc").mkdir()
    (tmp_path / "proc" / "WRAPIT.prc").write_text(
        "//WRAPIT PROC\n"
        "//P1 EXEC PGM=IEFBR14\n"
        "//D DD DSN=J.X,DISP=(NEW,DELETE,DELETE)\n"
        "// PEND\n"
    )
    job = Job(name="J", steps=(Step(name="STEP1", pgm="WRAPIT", dds=()),))
    runner = JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
        proclib_dirs=[tmp_path / "proc"],
    )
    res = runner.run(job, workdir=tmp_path, seeds={})
    assert [s.name for s in res.steps] == ["STEP1.P1"]
    assert res.steps[0].ran and res.steps[0].return_code == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_runner_without_proclib_dirs_is_unchanged(tmp_path: Path) -> None:
    # Default proclib_dirs=() must produce byte-identical behavior to every
    # existing call site that predates this feature (this is the exact body
    # of test_runner_runs_all_steps, re-run with no proclib_dirs argument).
    job = Job(
        name="J",
        steps=(
            Step(name="A", pgm="IEFBR14", dds=()),
            Step(name="B", pgm="IEFBR14", dds=()),
        ),
    )
    runner = JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )
    res = runner.run(job, workdir=tmp_path, seeds={})
    assert [s.name for s in res.steps] == ["A", "B"]
