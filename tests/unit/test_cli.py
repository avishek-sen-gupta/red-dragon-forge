"""Tests for the jackal CLI entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from tests.covers import covers, NotLanguageFeature

from jackal.cli import main


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_runs_utility_job(tmp_path, capsys):
    jcl = tmp_path / "j.jcl"
    jcl.write_text(
        "//J JOB 1\n//A EXEC PGM=IEFBR14\n//D DD DSN=J.X,DISP=(NEW,DELETE,DELETE)\n"
    )
    rc = main(["run", str(jcl), "--source-dir", str(tmp_path)])
    assert rc == 0
    assert "A" in capsys.readouterr().out


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_console_script_entry(tmp_path, capsys, monkeypatch):
    jcl = tmp_path / "j.jcl"
    jcl.write_text(
        "//J JOB 1\n//A EXEC PGM=IEFBR14\n//D DD DSN=J.X,DISP=(NEW,DELETE,DELETE)\n"
    )
    monkeypatch.setattr(
        sys, "argv", ["jackal", "run", str(jcl), "--source-dir", str(tmp_path)]
    )
    rc = main()
    assert rc == 0
    assert "A" in capsys.readouterr().out
