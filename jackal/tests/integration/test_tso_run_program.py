"""Integration tests: a TSO monitor step runs each DSN RUN PROGRAM named in its SYSTSIN."""

from pathlib import Path

import pytest
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.parser import parse_jcl
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.model import SystemAbend
from jackal.results import Abended, Completed
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy
from tests.covers import NotLanguageFeature, covers
from tests.package_build import package
from tests.system_build import scratch, system

_RC4 = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RC4.
       PROCEDURE DIVISION.
           MOVE 4 TO RETURN-CODE.
           STOP RUN.
"""
_RC0 = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RC0.
       PROCEDURE DIVISION.
           STOP RUN.
"""


@pytest.fixture(autouse=True)
def _require(bridge_jar, jcl_bridge_jar):
    """Both JARs are required: the JCL is parsed and the programs compiled."""


def _step(monitor: str, *runs: str) -> str:
    cards = "".join(f"  RUN PROGRAM({p}) PLAN(PLANX)\n" for p in runs)
    return (
        f"//S EXEC PGM={monitor}\n"
        "//SYSTSPRT DD SYSOUT=*\n"
        "//SYSTSIN DD *\n"
        f"  DSN SYSTEM(DB2P)\n{cards}  END\n/*\n"
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_tso_step_runs_its_programs_and_ends_with_the_highest_code(
    tmp_path: Path, bridge_jar
):
    """Records T2/T3: the session's code is the highest program code; an abend
    ends it, giving 12 under IKJEFT01 and S04C under IKJEFT1B."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "RC4.cbl").write_text(_RC4)
    (src / "RC0.cbl").write_text(_RC0)
    runner = JobRunner(
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        package=package(tmp_path / "package", ("RC4", "RC0"), src),
        system=system(tmp_path),
    )

    def outcome(step: str):
        job = parse_jcl("//J JOB 1\n" + step)
        return runner.run(job, scratch=scratch(tmp_path)).steps[0].outcome

    assert (
        outcome(_step("IKJEFT01", "RC4", "RC0")),
        outcome(_step("IKJEFT1A", "RC0")),
        outcome(_step("IKJEFT01", "NOSUCH", "RC4")),
        outcome(_step("IKJEFT1B", "NOSUCH", "RC4")),
    ) == (Completed(4), Completed(0), Completed(12), Abended(SystemAbend(0x04C)))
