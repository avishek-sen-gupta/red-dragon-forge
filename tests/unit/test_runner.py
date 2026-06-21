from pathlib import Path

from tests.covers import NotLanguageFeature, covers

from jackal.catalog import DatasetOrg
from jackal.model import DD, Disp, DispNormal, DispStatus, Job, Step
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
    catalog = runner._last_catalog  # exposed for test inspection
    ds = catalog.resolve("MYAPP.ACCOUNTS")
    assert ds.org == DatasetOrg.KSDS
