from pathlib import Path

import pytest
from catnip.labels import RecordFormat, SequentialLabel
from interpreter.cobol.ebcdic_table import EbcdicTable
from interpreter.vm.builtins import core_builtins
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET, run_cobol_step
from jackal.results import Completed
from tests.covers import NotLanguageFeature, covers
from tests.model_build import allocated, dd, disp, program
from tests.package_build import compiled, package
from tests.system_build import job_catalog, upload


def _ebcdic(text: bytes) -> bytes:
    """ASCII text -> its EBCDIC byte image (datasets are byte-faithful EBCDIC)."""
    return bytes(EbcdicTable.ascii_to_ebcdic(text))


@pytest.fixture(autouse=True)
def _require_bridge(bridge_jar):
    """Enforce PROLEAP_BRIDGE_JAR."""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cobol_step_reads_transforms_writes(tmp_path, bridge_jar):
    upload(
        tmp_path, "J.IN", _ebcdic(b"applemango"), SequentialLabel(RecordFormat.FB, 5)
    )
    cat = job_catalog(tmp_path)
    step = program(
        "S1",
        "COPYUP",
        (dd("INDD", "J.IN", disp("SHR")), dd("OUTDD", "J.OUT", disp("NEW", "PASS"))),
    )
    rc = run_cobol_step(
        step,
        compiled(package(tmp_path / "package", bridge_jar, ("COPYUP",)), "COPYUP"),
        allocated(step, cat),
        cat.workdir,
        budget=DEFAULT_PROGRAM_STEP_BUDGET,
        relabeller=cat,
        builtins=core_builtins(),
    )
    assert rc == Completed(0)
    assert cat.resolve("J.OUT").path.read_bytes() == _ebcdic(b"APPLEMANGO")
