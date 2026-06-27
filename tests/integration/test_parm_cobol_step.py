"""Integration tests: PARM= injection into COBOL LINKAGE via run_linked."""

from __future__ import annotations

from pathlib import Path

import pytest

from jackal.catalog import DatasetCatalog
from jackal.cobol_step import run_cobol_step
from jackal.model import Step
from tests.covers import NotLanguageFeature, covers

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
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    # Pad to 10 chars so the region exactly fills PARM-DATA PIC X(10)
    step = Step(name="S", pgm="TESTPARM", dds=(), parm="HELLO     ")
    result = run_cobol_step(step, _PARM_PROGRAM, cat, bridge_jar, [])
    assert result.return_code == 42


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_no_parm_step_runs_unchanged(tmp_path, bridge_jar):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    step = Step(name="S", pgm="NOPARM", dds=())
    result = run_cobol_step(step, _NO_PARM_PROGRAM, cat, bridge_jar, [])
    assert result.return_code == 7
