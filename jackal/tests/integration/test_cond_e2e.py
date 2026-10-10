from pathlib import Path

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.jcl.parser import parse_jcl
from jackal.results import StepDisposition
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy

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
        source_dir=src,
        bridge_jar=bridge_jar,
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )
    res = runner.run(job, workdir=tmp_path, seeds={})
    a, b = res.steps
    assert a.return_code == 8 and a.disposition is StepDisposition.EXECUTED
    assert b.disposition is StepDisposition.BYPASSED  # COND=(0,NE) bypassed after RC 8
