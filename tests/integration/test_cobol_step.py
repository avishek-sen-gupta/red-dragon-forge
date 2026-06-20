from pathlib import Path

import pytest

from jackal.catalog import DatasetCatalog
from jackal.cobol_step import run_cobol_step
from jackal.model import DD, Disp, DispNormal, DispStatus, Step
from tests.covers import NotLanguageFeature, covers

CBL = Path(__file__).parent / "fixtures" / "cbl"


@pytest.fixture(autouse=True)
def _require_bridge(bridge_jar):
    """Enforce PROLEAP_BRIDGE_JAR."""


def _dd(ddname, dsn, status, normal=DispNormal.KEEP):
    return DD(ddname=ddname, dsn=dsn, disp=Disp(status, normal, DispNormal.DELETE))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cobol_step_reads_transforms_writes(tmp_path, bridge_jar):
    src = tmp_path / "in.dat"
    src.write_bytes(b"applemango")  # two 5-byte records
    cat = DatasetCatalog(workdir=tmp_path)
    cat.seed("J.IN", src)
    step = Step(
        name="S1",
        pgm="COPYUP",
        dds=(
            _dd("INDD", "J.IN", DispStatus.SHR),
            _dd("OUTDD", "J.OUT", DispStatus.NEW, DispNormal.PASS),
        ),
    )
    result = run_cobol_step(step, (CBL / "COPYUP.cbl").read_text(), cat, bridge_jar)
    assert result.ran and result.return_code == 0
    assert cat.resolve("J.OUT").path.read_bytes() == b"APPLEMANGO"
