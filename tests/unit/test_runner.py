from pathlib import Path

from tests.covers import NotLanguageFeature, covers

from jackal.model import DD, Cond, CondOp, Disp, DispNormal, DispStatus, Job, Step
from jackal.results import StepDisposition
from jackal.runner import JobRunner

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
                        "J.X",
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
                dsn="",
                disp=_DUMMY_DISP,
                in_stream=sysin_lines,
            ),
            DD(
                ddname="SYSPRINT",
                dsn="",
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
                dsn="",
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
