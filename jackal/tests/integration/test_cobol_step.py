from pathlib import Path

import pytest

from interpreter.cobol.ebcdic_table import EbcdicTable
from jackal.catalog import DatasetCatalog
from jackal.cobol_step import run_cobol_step
from tests.model_build import allocated, dd, disp, program
from tests.covers import NotLanguageFeature, covers

CBL = Path(__file__).parent / "fixtures" / "cbl"


def _ebcdic(text: bytes) -> bytes:
    """ASCII text -> its EBCDIC byte image (datasets are byte-faithful EBCDIC)."""
    return bytes(EbcdicTable.ascii_to_ebcdic(text))


@pytest.fixture(autouse=True)
def _require_bridge(bridge_jar):
    """Enforce PROLEAP_BRIDGE_JAR."""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cobol_step_reads_transforms_writes(tmp_path, bridge_jar):
    src = tmp_path / "in.dat"
    src.write_bytes(_ebcdic(b"applemango"))  # two 5-byte records, EBCDIC
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    cat.seed("J.IN", src)
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
    )
    assert rc == 0
    assert cat.resolve("J.OUT").path.read_bytes() == _ebcdic(b"APPLEMANGO")
