from pathlib import Path

import pytest
from jackal.allocation import DdEnvironment
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET, run_cobol_step
from jackal.results import Completed
from tests.covers import NotLanguageFeature, covers
from tests.model_build import program
from tests.package_build import compiled, package
from tests.system_build import job_catalog
from interpreter.vm.builtins import core_builtins

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
    cat = job_catalog(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "SETRC.cbl").write_text(_PGM)
    assert run_cobol_step(
        program("S", "SETRC"),
        compiled(package(tmp_path / "package", bridge_jar, ("SETRC",), src), "SETRC"),
        DdEnvironment(()),
        cat.workdir,
        DEFAULT_PROGRAM_STEP_BUDGET,
        cat,
        builtins=core_builtins(),
    ) == Completed(8)
