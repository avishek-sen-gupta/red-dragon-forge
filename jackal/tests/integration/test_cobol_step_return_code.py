from pathlib import Path

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.catalog import DatasetCatalog
from jackal.cobol_step import run_cobol_step
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
    assert run_cobol_step(program("S", "SETRC"), _PGM, cat, bridge_jar, []) == 8
