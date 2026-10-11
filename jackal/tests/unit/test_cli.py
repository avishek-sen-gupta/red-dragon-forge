"""Tests for the jackal CLI entry point."""

from __future__ import annotations

import sys
from pathlib import Path

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
            "--data-dir",
            str(tmp_path),
            "--copybook-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert "A" in capsys.readouterr().out


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
            "--data-dir",
            str(tmp_path),
            "--copybook-dir",
            str(tmp_path),
        ],
    )
    rc = main()
    assert rc == 0
    assert "A" in capsys.readouterr().out


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_cleans_up_workdir(tmp_path, monkeypatch):
    from jackal.results import JobResult
    from jackal.runner import JobRunner

    captured: dict = {}

    def fake_run(self, job, workdir, seeds):
        captured["workdir"] = Path(workdir)
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
            "--data-dir",
            str(tmp_path),
            "--copybook-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert not captured["workdir"].exists()  # removed after main returns


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_runs_past_a_missing_dataset_and_a_missing_program(tmp_path, capsys):
    jcl = tmp_path / "j.jcl"
    jcl.write_text(
        "//J JOB 1\n//A EXEC PGM=IEFBR14\n//D DD DSN=NO.SUCH,DISP=SHR\n"
        "//B EXEC PGM=SORT\n"
    )
    rc = run(
        [
            "run",
            str(jcl),
            "--source-dir",
            str(tmp_path),
            "--data-dir",
            str(tmp_path),
            "--copybook-dir",
            str(tmp_path),
        ]
    )
    assert (rc, capsys.readouterr().out) == (0, "A: RC=0\nB: RC=0\n")
