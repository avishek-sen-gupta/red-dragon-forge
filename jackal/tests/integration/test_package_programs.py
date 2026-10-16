"""A step takes its program from the package; a program the package lacks is a missing program."""

import logging
from pathlib import Path

import pytest
from jackal.cli import run
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.missing_data import StrictAllocation
from jackal.missing_program import (
    AbendMissingProgram,
    MissingProgramStrategy,
    StubMissingProgram,
)
from jackal.results import Abended, Completed, StepOutcome, SystemAbend
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy
from litter.package import Package
from tests.covers import NotLanguageFeature, covers
from tests.model_build import job, program
from tests.package_build import built, package
from tests.system_build import scratch, system

_PGMA = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PGMA.
       PROCEDURE DIVISION.
           STOP RUN.
"""
_SETRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SETRC.
       PROCEDURE DIVISION.
           MOVE 8 TO RETURN-CODE.
           STOP RUN.
"""


@pytest.fixture(autouse=True)
def _require(bridge_jar: str) -> None:
    """The bridge JAR builds every package in this module."""


@pytest.fixture(scope="module")
def pgma_only(tmp_path_factory: pytest.TempPathFactory, bridge_jar: str) -> Package:
    src = tmp_path_factory.mktemp("src")
    (src / "PGMA.cbl").write_text(_PGMA)
    return package(
        tmp_path_factory.mktemp("package"), bridge_jar, ("PGMA",), cbl_dir=src
    )


def _outcomes(
    root: Path, packaged: Package, missing_program: MissingProgramStrategy
) -> list[StepOutcome]:
    runner = JobRunner(
        package=packaged,
        system=system(root),
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=missing_program,
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
    )
    two_steps = job("J", (program("S1", "PGMA"), program("S2", "PGMB")))
    return [s.outcome for s in runner.run(two_steps, scratch(root)).steps]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_program_the_package_lacks_is_a_missing_program(
    tmp_path: Path, pgma_only: Package, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="jackal.missing_program"):
        stubbed = _outcomes(tmp_path / "stub", pgma_only, StubMissingProgram())
    warnings = caplog.messages
    abended = _outcomes(tmp_path / "abend", pgma_only, AbendMissingProgram())

    assert (stubbed, warnings, abended) == (
        [Completed(0), Completed(0)],
        ["S2: no program PGMB; stubbed with RC 0"],
        [Completed(0), Abended(SystemAbend(0x806))],
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_the_cli_runs_a_job_against_the_package_it_is_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], bridge_jar: str
) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "SETRC.cbl").write_text(_SETRC)
    jcl = tmp_path / "j.jcl"
    jcl.write_text("//J JOB 1\n//A EXEC PGM=SETRC\n//B EXEC PGM=NOSUCH\n")
    rc = run(
        [
            "run",
            str(jcl),
            "--package",
            str(built(tmp_path / "package", bridge_jar, ("SETRC",), cbl_dir=src)),
            "--system",
            str(tmp_path / "system"),
        ]
    )
    assert (rc, capsys.readouterr().out) == (1, "A: RC=8\nB: RC=0\n")
