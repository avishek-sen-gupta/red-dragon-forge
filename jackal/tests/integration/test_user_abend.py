"""Integration tests: a COBOL program ends its step with a user abend by calling LE's CEE3ABD."""

from pathlib import Path

import pytest
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.parser import parse_jcl
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.model import UserAbend
from jackal.results import Abended, AfterAbend, Completed, Flushed
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy
from tests.covers import NotLanguageFeature, covers
from tests.package_build import package
from tests.system_build import scratch, system

_ABEND = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ABEND999.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 ABCODE PIC S9(9) BINARY VALUE 999.
       01 TIMING PIC S9(9) BINARY VALUE 0.
       PROCEDURE DIVISION.
           CALL 'CEE3ABD' USING ABCODE, TIMING.
           MOVE 7 TO RETURN-CODE.
           STOP RUN.
"""
_BARE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BAREABD.
       PROCEDURE DIVISION.
           CALL 'CEE3ABD'.
           STOP RUN.
"""
_OK = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OK.
       PROCEDURE DIVISION.
           STOP RUN.
"""


@pytest.fixture(autouse=True)
def _require(bridge_jar, jcl_bridge_jar):
    """Both JARs are required: the JCL is parsed and the programs compiled."""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cee3abd_abends_the_step_with_its_user_code(tmp_path: Path, bridge_jar):
    """LE Programming Reference, CEE3ABD: the enclave ends with the abend code and
    the service never returns. The abend reaches IF ABENDCC and flushes the
    ordinary step after it; a bare CALL passes no code and abends U0000."""
    src = tmp_path / "src"
    src.mkdir()
    for name, text in (("ABEND999", _ABEND), ("BAREABD", _BARE), ("OK", _OK)):
        (src / f"{name}.cbl").write_text(text)
    runner = JobRunner(
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        package=package(tmp_path / "package", ("ABEND999", "BAREABD", "OK"), src),
        system=system(tmp_path),
    )
    jcl = (
        "//J JOB 1\n"
        "//S1 EXEC PGM=ABEND999\n"
        "// IF S1.ABENDCC=U0999 THEN\n"
        "//S2 EXEC PGM=OK\n"
        "// ENDIF\n"
        "//S3 EXEC PGM=OK\n"
    )
    steps = runner.run(parse_jcl(jcl), scratch=scratch(tmp_path)).steps
    bare = runner.run(
        parse_jcl("//J JOB 1\n//S1 EXEC PGM=BAREABD\n"), scratch=scratch(tmp_path)
    ).steps
    assert [s.outcome for s in steps] == [
        Abended(UserAbend(999)),
        Completed(0),
        Flushed(AfterAbend(steps[0].step)),
    ]
    assert [s.outcome for s in bare] == [Abended(UserAbend(0))]
    assert Abended(UserAbend(999)).rendered() == "abended U0999"
