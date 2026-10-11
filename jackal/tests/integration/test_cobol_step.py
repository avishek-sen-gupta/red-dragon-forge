from pathlib import Path

import pytest
from interpreter.cobol.ebcdic_table import EbcdicTable
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET, run_cobol_step
from jackal.labels import RecordFormat, SequentialLabel
from jackal.results import Completed
from tests.covers import NotLanguageFeature, covers
from tests.model_build import allocated, dd, disp, program
from tests.system_build import job_catalog, upload

CBL = Path(__file__).parent / "fixtures" / "cbl"


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
        (CBL / "COPYUP.cbl").read_text(),
        allocated(step, cat),
        cat.workdir,
        bridge_jar,
        copybook_dirs=[],
        budget=DEFAULT_PROGRAM_STEP_BUDGET,
    )
    assert rc == Completed(0)
    assert cat.resolve("J.OUT").path.read_bytes() == _ebcdic(b"APPLEMANGO")
