"""Tests for the jackal CLI entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from catnip.dataset import Dataset
from catnip.labels import LabelPending, RecordFormat, SequentialLabel
from catnip.system_catalog import SystemCatalog
from jackal.cli import main, run
from tests.covers import NotLanguageFeature, covers
from tests.package_build import built


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_runs_utility_job(tmp_path, capsys, bridge_jar):
    jcl = tmp_path / "j.jcl"
    jcl.write_text(
        "//J JOB 1\n//A EXEC PGM=IEFBR14\n//D DD DSN=J.X,DISP=(NEW,DELETE,DELETE)\n"
    )
    rc = run(
        [
            "run",
            str(jcl),
            "--package",
            str(built(tmp_path, bridge_jar, ())),
            "--system",
            str(tmp_path / "system"),
        ]
    )
    assert (rc, capsys.readouterr().out) == (0, "A: RC=0\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_console_script_entry(tmp_path, capsys, monkeypatch, bridge_jar):
    jcl = tmp_path / "j.jcl"
    jcl.write_text(
        "//J JOB 1\n//A EXEC PGM=IEFBR14\n//D DD DSN=J.X,DISP=(NEW,DELETE,DELETE)\n"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "jackal",
            "run",
            str(jcl),
            "--package",
            str(built(tmp_path, bridge_jar, ())),
            "--system",
            str(tmp_path / "system"),
        ],
    )
    rc = main()
    assert (rc, capsys.readouterr().out) == (0, "A: RC=0\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_cleans_up_workdir(tmp_path, monkeypatch, bridge_jar):
    from jackal.results import JobResult
    from jackal.runner import JobRunner

    captured: dict = {}

    def fake_run(self, job, scratch):
        captured["workdir"] = Path(scratch)
        assert captured["workdir"].exists()  # present during the run
        return JobResult(steps=())

    monkeypatch.setattr(JobRunner, "run", fake_run)
    jcl = tmp_path / "j.jcl"
    jcl.write_text("//J JOB 1\n//A EXEC PGM=IEFBR14\n")
    rc = run(
        [
            "run",
            str(jcl),
            "--package",
            str(built(tmp_path, bridge_jar, ())),
            "--system",
            str(tmp_path / "system"),
        ]
    )
    assert rc == 0
    assert not captured["workdir"].exists()  # removed after main returns


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_catalogs_a_dataset_then_runs_a_job_that_changes_the_system(
    tmp_path, capsys, bridge_jar
):
    upload = tmp_path / "in.dat"
    upload.write_bytes(b"x" * 80)
    system = tmp_path / "system"
    added = run(
        [
            "catalog",
            "add",
            "J.IN",
            "--system",
            str(system),
            "--file",
            str(upload),
            "--recfm",
            "FB",
            "--lrecl",
            "80",
        ]
    )
    jcl = tmp_path / "j.jcl"
    jcl.write_text(
        "//J JOB 1\n//A EXEC PGM=IEFBR14\n//I DD DSN=J.IN,DISP=SHR\n"
        "//O DD DSN=J.OUT,DISP=(NEW,CATLG)\n//M DD DSN=NO.SUCH,DISP=SHR\n"
        "//B EXEC PGM=SORT\n"
    )
    ran = run(
        [
            "run",
            str(jcl),
            "--system",
            str(system),
            "--package",
            str(built(tmp_path, bridge_jar, ())),
        ]
    )
    catalog = SystemCatalog(system)
    datasets = system / "datasets"
    assert (
        added,
        ran,
        capsys.readouterr().out,
        catalog.lookup("J.IN"),
        catalog.lookup("J.OUT"),
        catalog.lookup("NO.SUCH"),
    ) == (
        0,
        0,
        "A: RC=0\nB: RC=0\n",
        Dataset("J.IN", datasets / "J.IN", SequentialLabel(RecordFormat.FB, 80)),
        Dataset("J.OUT", datasets / "J.OUT", LabelPending()),
        Dataset("NO.SUCH", datasets / "NO.SUCH", LabelPending()),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_expands_procs_from_its_proclib_and_reports_an_unresolved_one(
    tmp_path, capsys, bridge_jar
):
    import pytest

    procs = tmp_path / "proc"
    procs.mkdir()
    (procs / "MKPROC.prc").write_text(
        "//MKPROC PROC\n//PS EXEC PGM=IEFBR14\n//D DD DSN=J.X,DISP=(NEW,DELETE)\n"
    )
    jcl = tmp_path / "j.jcl"
    jcl.write_text("//J JOB 1\n//S1 EXEC MKPROC\n")
    common = [
        "run",
        str(jcl),
        "--package",
        str(built(tmp_path, bridge_jar, ())),
        "--system",
        str(tmp_path / "system"),
    ]
    assert (run([*common, "--proclib", str(procs)]), capsys.readouterr().out) == (
        0,
        "S1.PS: RC=0\n",
    )
    with pytest.raises(SystemExit) as exited:
        run([*common, "--proclib", str(tmp_path)])
    assert (exited.value.code, capsys.readouterr().err) == (
        1,
        "jackal: S1: PROC MKPROC is in no proclib (blueprint D7)\n",
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_package_that_cannot_be_opened_is_an_argument_error(tmp_path, capsys):
    import pytest

    jcl = tmp_path / "j.jcl"
    jcl.write_text("//J JOB 1\n//A EXEC PGM=IEFBR14\n")
    missing = tmp_path / "missing.zip"
    not_a_zip = tmp_path / "text.zip"
    not_a_zip.write_text("not a zip")

    def refused(package):
        with pytest.raises(SystemExit) as stopped:
            run(["run", str(jcl), "--package", str(package), "--system", "s"])
        return stopped.value.code, capsys.readouterr().err.splitlines()[-1]

    assert (refused(missing), refused(not_a_zip)) == (
        (
            2,
            f"jackal: error: --package {missing}: "
            f"[Errno 2] No such file or directory: '{missing}'",
        ),
        (2, f"jackal: error: --package {not_a_zip}: File is not a zip file"),
    )
