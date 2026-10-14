"""Tests for the jackal CLI entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from catnip.dataset import Dataset
from catnip.labels import LabelPending, RecordFormat, SequentialLabel
from catnip.system_catalog import SystemCatalog
from jackal.cli import main, run
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_runs_utility_job(tmp_path, capsys):
    jcl = tmp_path / "j.jcl"
    jcl.write_text(
        "//J JOB 1\n//A EXEC PGM=IEFBR14\n//D DD DSN=J.X,DISP=(NEW,DELETE,DELETE)\n"
    )
    rc = run(
        [
            "run",
            str(jcl),
            "--source-dir",
            str(tmp_path),
            "--system",
            str(tmp_path / "system"),
            "--copybook-dir",
            str(tmp_path),
        ]
    )
    assert (rc, capsys.readouterr().out) == (0, "A: RC=0\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_console_script_entry(tmp_path, capsys, monkeypatch):
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
            "--source-dir",
            str(tmp_path),
            "--system",
            str(tmp_path / "system"),
            "--copybook-dir",
            str(tmp_path),
        ],
    )
    rc = main()
    assert (rc, capsys.readouterr().out) == (0, "A: RC=0\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_cleans_up_workdir(tmp_path, monkeypatch):
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
            "--source-dir",
            str(tmp_path),
            "--system",
            str(tmp_path / "system"),
            "--copybook-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert not captured["workdir"].exists()  # removed after main returns


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_catalogs_a_dataset_then_runs_a_job_that_changes_the_system(
    tmp_path, capsys
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
            "--source-dir",
            str(tmp_path),
            "--copybook-dir",
            str(tmp_path),
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
def test_cli_refuses_a_link_list_naming_a_program_with_no_source(tmp_path, capsys):
    import pytest

    (tmp_path / "SUBPGM.cbl").write_text("")
    jcl = tmp_path / "j.jcl"
    jcl.write_text("//J JOB 1\n//A EXEC PGM=IEFBR14\n")
    with pytest.raises(SystemExit) as exited:
        run(
            [
                "run",
                str(jcl),
                "--source-dir",
                str(tmp_path),
                "--system",
                str(tmp_path / "system"),
                "--copybook-dir",
                str(tmp_path),
                "--link",
                "SUBPGM",
                "NOSUCH",
            ]
        )
    assert (exited.value.code, capsys.readouterr()) == (
        2,
        (
            "",
            "usage: jackal [-h] {run,catalog} ...\n"
            "jackal: error: --link: no COBOL source for linked program NOSUCH\n",
        ),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_expands_procs_from_its_proclib_and_reports_an_unresolved_one(
    tmp_path, capsys
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
        "--source-dir",
        str(tmp_path),
        "--system",
        str(tmp_path / "system"),
        "--copybook-dir",
        str(tmp_path),
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
