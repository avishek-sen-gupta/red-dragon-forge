"""Integration tests: PARM= injection into COBOL LINKAGE via run_linked."""

from __future__ import annotations

from jackal.allocation import DdEnvironment
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET, run_cobol_step
from jackal.results import Completed
from tests.covers import NotLanguageFeature, covers
from tests.model_build import program
from tests.package_build import compiled, package
from tests.system_build import job_catalog

# Minimal COBOL program that reads PARM-DATA and signals receipt via RETURN-CODE.
# PARM-LENGTH (S9(04) COMP) is a 2-byte big-endian halfword — matches build_parm_region.
# When PARM-DATA = 'HELLO     ', sets RETURN-CODE = 42; else 0.
_PARM_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPARM.
       DATA DIVISION.
       LINKAGE SECTION.
       01  PARM-AREA.
           05  PARM-LENGTH  PIC S9(04) COMP.
           05  PARM-DATA    PIC X(10).
       PROCEDURE DIVISION USING PARM-AREA.
           IF PARM-DATA = 'HELLO     '
               MOVE 42 TO RETURN-CODE
           ELSE
               MOVE 0 TO RETURN-CODE
           END-IF
           STOP RUN.
"""

# Minimal COBOL program with no LINKAGE — tests the no-PARM path is unchanged.
_NO_PARM_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOPARM.
       PROCEDURE DIVISION.
           MOVE 7 TO RETURN-CODE.
           STOP RUN.
"""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parm_received_in_cobol_linkage(tmp_path, bridge_jar):
    cat = job_catalog(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "TESTPARM.cbl").write_text(_PARM_PROGRAM)
    # Pad to 10 chars so the region exactly fills PARM-DATA PIC X(10)
    step = program("S", "TESTPARM", parm="HELLO     ")
    assert run_cobol_step(
        step,
        compiled(
            package(tmp_path / "package", bridge_jar, ("TESTPARM",), src), "TESTPARM"
        ),
        DdEnvironment(()),
        cat.workdir,
        DEFAULT_PROGRAM_STEP_BUDGET,
        cat,
    ) == Completed(42)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_no_parm_step_runs_unchanged(tmp_path, bridge_jar):
    cat = job_catalog(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "NOPARM.cbl").write_text(_NO_PARM_PROGRAM)
    assert run_cobol_step(
        program("S", "NOPARM"),
        compiled(package(tmp_path / "package", bridge_jar, ("NOPARM",), src), "NOPARM"),
        DdEnvironment(()),
        cat.workdir,
        DEFAULT_PROGRAM_STEP_BUDGET,
        cat,
    ) == Completed(7)
