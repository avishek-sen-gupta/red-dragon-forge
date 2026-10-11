from pathlib import Path

import pytest
from jackal.allocation import DdEnvironment
from jackal.catalog import DatasetCatalog
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET, run_cobol_step
from jackal.results import Completed
from tests.covers import NotLanguageFeature, covers
from tests.model_build import program

_PGM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SETRC.
       PROCEDURE DIVISION.
           MOVE 8 TO RETURN-CODE.
           STOP RUN.
"""


@pytest.fixture(autouse=True)
def _require_bridge(bridge_jar):
    """Enforce PROLEAP_BRIDGE_JAR."""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cobol_step_returns_real_return_code(tmp_path: Path, bridge_jar):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    assert run_cobol_step(
        program("S", "SETRC"),
        _PGM,
        DdEnvironment(()),
        cat.workdir,
        bridge_jar,
        [],
        DEFAULT_PROGRAM_STEP_BUDGET,
    ) == Completed(8)
