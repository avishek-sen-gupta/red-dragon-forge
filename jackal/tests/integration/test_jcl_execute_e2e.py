"""Full JCL-to-execute end-to-end tests: JCL text → ANTLR bridge → JobRunner.

Each test exercises one language feature through the complete parse-and-run
pipeline so that a regression in either the Java bridge or the runner is caught
by a real JCL job, not just model-object construction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jackal.jcl.bridge_parser import JclBridgeParser, JclSubprocessRunner
from jackal.results import StepDisposition
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy
from tests.covers import NotLanguageFeature, covers

# Minimal COBOL that reads PARM-DATA and sets RETURN-CODE=42 when it equals 'HELLO     '.
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


@pytest.fixture(autouse=True)
def _require(bridge_jar, jcl_bridge_jar):
    """Both JARs are required for every test in this module."""


def _parse(jcl: str, jcl_bridge_jar: str):
    return JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)


def _runner(src: Path, bridge_jar: str, tmp_path: Path) -> JobRunner:
    return JobRunner(
        unresolved=RaiseErrorStrategy(),
        source_dir=src,
        bridge_jar=bridge_jar,
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )


# ---------------------------------------------------------------------------
# Feature: PARM= (jackal-1o2.13)
# ---------------------------------------------------------------------------


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parm_passed_through_jcl_bridge(tmp_path, bridge_jar, jcl_bridge_jar):
    """PARM='HELLO     ' in JCL reaches COBOL LINKAGE and sets RETURN-CODE=42."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "TESTPARM.cbl").write_text(_PARM_PROGRAM)

    jcl = "//J JOB 1\n//STEP1 EXEC PGM=TESTPARM,PARM='HELLO     '\n"
    job = _parse(jcl, jcl_bridge_jar)
    result = _runner(src, bridge_jar, tmp_path).run(job, workdir=tmp_path, seeds={})

    assert len(result.steps) == 1
    assert result.steps[0].ran
    assert result.steps[0].return_code == 42


# ---------------------------------------------------------------------------
# Feature: &&NAME temporary datasets (jackal-1o2.11)
# ---------------------------------------------------------------------------


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_dataset_lifecycle_via_jcl_bridge(tmp_path, bridge_jar, jcl_bridge_jar):
    """Two-step JCL with DSN=&&TEMP: step 1 creates, step 2 deletes; workdir clean."""
    jcl = (
        "//J JOB 1\n"
        "//STEP1 EXEC PGM=IEFBR14\n"
        "//WRK    DD DSN=&&TEMP,DISP=(NEW,PASS,DELETE)\n"
        "//STEP2 EXEC PGM=IEFBR14\n"
        "//WRK    DD DSN=&&TEMP,DISP=(OLD,DELETE,DELETE)\n"
    )
    job = _parse(jcl, jcl_bridge_jar)
    result = _runner(tmp_path, bridge_jar, tmp_path).run(
        job, workdir=tmp_path, seeds={}
    )

    assert all(s.ran and s.return_code == 0 for s in result.steps)
    assert not (tmp_path / "TEMP").exists()


# ---------------------------------------------------------------------------
# Feature: backward references DSN=*.STEP.DD (jackal-1o2.10)
# ---------------------------------------------------------------------------


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_backward_ref_resolves_via_jcl_bridge(tmp_path, bridge_jar, jcl_bridge_jar):
    """DSN=*.STEP1.WRK in step 2 resolves to step 1's dataset; both steps run."""
    jcl = (
        "//J JOB 1\n"
        "//STEP1 EXEC PGM=IEFBR14\n"
        "//WRK    DD DSN=MY.WORK.FILE,DISP=(NEW,PASS,DELETE)\n"
        "//STEP2 EXEC PGM=IEFBR14\n"
        "//INPUT  DD DSN=*.STEP1.WRK,DISP=(OLD,DELETE,DELETE)\n"
    )
    job = _parse(jcl, jcl_bridge_jar)
    result = _runner(tmp_path, bridge_jar, tmp_path).run(
        job, workdir=tmp_path, seeds={}
    )

    step1, step2 = result.steps
    assert step1.ran and step1.return_code == 0
    assert step2.ran and step2.return_code == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_backward_ref_bypass_propagation_via_jcl_bridge(
    tmp_path, bridge_jar, jcl_bridge_jar
):
    """When step 1 is bypassed, step 2 referencing *.STEP1.WRK is also bypassed."""
    jcl = (
        "//J JOB 1\n"
        "//STEP0 EXEC PGM=IEFBR14\n"
        "//STEP1 EXEC PGM=IEFBR14,COND=(0,GE,STEP0)\n"
        "//WRK    DD DSN=MY.WORK.FILE,DISP=(NEW,PASS,DELETE)\n"
        "//STEP2 EXEC PGM=IEFBR14\n"
        "//INPUT  DD DSN=*.STEP1.WRK,DISP=(OLD,DELETE,DELETE)\n"
    )
    job = _parse(jcl, jcl_bridge_jar)
    result = _runner(tmp_path, bridge_jar, tmp_path).run(
        job, workdir=tmp_path, seeds={}
    )

    step0, step1, step2 = result.steps
    assert step0.ran
    assert step1.disposition is StepDisposition.BYPASSED
    assert step2.disposition is StepDisposition.BYPASSED
