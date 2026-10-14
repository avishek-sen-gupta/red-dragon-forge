"""A batch program reads a cluster through a path, in alternate-key order."""

from pathlib import Path

import pytest
from interpreter.cobol.ebcdic_table import EbcdicTable

from catnip.alternate_index import AlternateIndex
from catnip.catalog_path import CatalogPath
from catnip.labels import KsdsLabel
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET, run_cobol_step
from jackal.program_compiler import ProgramCompiler
from jackal.catalog import DatasetCatalog
from jackal.model import DD, StepRef
from jackal.results import Completed, ProgramResult
from tests.covers import NotLanguageFeature, covers
from tests.model_build import allocated, dd, disp, program
from tests.system_build import job_catalog, system, upload

CBL = Path(__file__).parent / "fixtures" / "cbl"


def _ebcdic(text: bytes) -> bytes:
    return bytes(EbcdicTable.ascii_to_ebcdic(text))


@pytest.fixture(autouse=True)
def _require_bridge(bridge_jar):
    """Enforce PROLEAP_BRIDGE_JAR."""


_BASE = _ebcdic(b"001BBBxx002AAAyy003AAAzz")


def _path_catalog(tmp_path: Path) -> DatasetCatalog:
    upload(tmp_path, "J.KSDS", _BASE, KsdsLabel(8, 0, 3))
    system(tmp_path).define_aix(AlternateIndex("J.AIX", "J.KSDS", 3, 3, False))
    system(tmp_path).define_path(CatalogPath("J.PATH", "J.AIX"))
    return job_catalog(tmp_path)


def _ran(
    cat: DatasetCatalog, bridge_jar: str, name: str, dds: tuple[DD[StepRef], ...]
) -> ProgramResult:
    step = program("S1", name, dds)
    return run_cobol_step(
        step,
        ProgramCompiler(bridge_jar, (), (CBL,), ()).compiled(
            (CBL / f"{name}.cbl").read_text()
        ),
        allocated(step, cat),
        cat.workdir,
        budget=DEFAULT_PROGRAM_STEP_BUDGET,
        relabeller=cat,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_program_reads_a_cluster_through_its_path(tmp_path, bridge_jar):
    cat = _path_catalog(tmp_path)
    rc = _ran(
        cat,
        bridge_jar,
        "ALTREAD",
        (
            dd("XREFDD", "J.PATH", disp("SHR")),
            dd("OUTDD", "J.OUT", disp("NEW", "PASS")),
        ),
    )

    assert rc == Completed(0)
    assert cat.resolve("J.OUT").path.read_bytes() == _ebcdic(
        b"002AAAyy003AAAzz001BBBxx"
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_open_output_through_a_path_gets_status_37_and_keeps_the_base_cluster(
    tmp_path, bridge_jar
):
    cat = _path_catalog(tmp_path)
    rc = _ran(cat, bridge_jar, "ALTLOAD", (dd("XREFDD", "J.PATH", disp("SHR")),))

    assert rc == Completed(37)
    assert system(tmp_path).lookup("J.KSDS").path.read_bytes() == _BASE
