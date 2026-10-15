from pathlib import Path

import pytest
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.parser import parse_jcl
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.results import Bypassed, BypassReason, Completed
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy
from tests.covers import NotLanguageFeature, covers
from tests.package_build import package
from tests.system_build import scratch, system

_FAIL_PGM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FAILS.
       PROCEDURE DIVISION.
           MOVE 8 TO RETURN-CODE.
           STOP RUN.
"""
_OK_PGM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OK.
       PROCEDURE DIVISION.
           STOP RUN.
"""


@pytest.fixture(autouse=True)
def _require(bridge_jar, jcl_bridge_jar):
    """Both JARs are required for this end-to-end COND test."""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cond_bypasses_real_cobol_step(tmp_path: Path, bridge_jar, jcl_bridge_jar):
    src = tmp_path / "src"
    src.mkdir()
    (src / "FAILS.cbl").write_text(_FAIL_PGM)
    (src / "OK.cbl").write_text(_OK_PGM)
    jcl = "//J JOB 1\n//A EXEC PGM=FAILS\n//B EXEC PGM=OK,COND=(0,NE)\n"
    job = parse_jcl(jcl)
    runner = JobRunner(
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        package=package(tmp_path / "package", ("FAILS", "OK"), src),
        system=system(tmp_path),
    )
    res = runner.run(job, scratch=scratch(tmp_path))
    a, b = res.steps
    assert a.outcome == Completed(8)
    assert b.outcome == Bypassed(BypassReason.COND_SATISFIED)
