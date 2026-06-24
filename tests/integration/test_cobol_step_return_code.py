from pathlib import Path

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.catalog import DatasetCatalog
from jackal.cobol_step import run_cobol_step
from jackal.model import Step

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
    step = Step(name="S", pgm="SETRC", dds=())
    res = run_cobol_step(step, _PGM, cat, bridge_jar, [])
    assert res.return_code == 8 and res.ran is True
