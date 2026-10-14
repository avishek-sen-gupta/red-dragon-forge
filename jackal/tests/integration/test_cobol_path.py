"""A batch program reads a cluster through a path, in alternate-key order."""

from pathlib import Path

import pytest
from interpreter.cobol.ebcdic_table import EbcdicTable

from catnip.alternate_index import AlternateIndex
from catnip.catalog_path import CatalogPath
from catnip.labels import KsdsLabel
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET, run_cobol_step
from jackal.program_compiler import ProgramCompiler
from jackal.results import Completed
from tests.covers import NotLanguageFeature, covers
from tests.model_build import allocated, dd, disp, program
from tests.system_build import job_catalog, system, upload

CBL = Path(__file__).parent / "fixtures" / "cbl"


def _ebcdic(text: bytes) -> bytes:
    return bytes(EbcdicTable.ascii_to_ebcdic(text))


@pytest.fixture(autouse=True)
def _require_bridge(bridge_jar):
    """Enforce PROLEAP_BRIDGE_JAR."""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_program_reads_a_cluster_through_its_path(tmp_path, bridge_jar):
    upload(
        tmp_path,
        "J.KSDS",
        _ebcdic(b"001BBBxx002AAAyy003AAAzz"),
        KsdsLabel(8, 0, 3),
    )
    system(tmp_path).define_aix(AlternateIndex("J.AIX", "J.KSDS", 3, 3, False))
    system(tmp_path).define_path(CatalogPath("J.PATH", "J.AIX"))
    cat = job_catalog(tmp_path)
    step = program(
        "S1",
        "ALTREAD",
        (
            dd("XREFDD", "J.PATH", disp("SHR")),
            dd("OUTDD", "J.OUT", disp("NEW", "PASS")),
        ),
    )
    rc = run_cobol_step(
        step,
        ProgramCompiler(bridge_jar, (), (CBL,), ()).compiled(
            (CBL / "ALTREAD.cbl").read_text()
        ),
        allocated(step, cat),
        cat.workdir,
        budget=DEFAULT_PROGRAM_STEP_BUDGET,
        relabeller=cat,
    )

    assert rc == Completed(0)
    assert cat.resolve("J.OUT").path.read_bytes() == _ebcdic(
        b"002AAAyy003AAAzz001BBBxx"
    )
