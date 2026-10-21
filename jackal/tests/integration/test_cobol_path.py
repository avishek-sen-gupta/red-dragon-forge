"""A batch program reads a cluster through a path, in alternate-key order."""

import logging
from pathlib import Path

import pytest
from interpreter.encoding.ebcdic_table import EbcdicTable
from interpreter.project.ir_codec import IrCodec
from interpreter.project.linked_codec import LinkedCodec
from interpreter.vm.builtins import core_builtins

from catnip.alternate_index import AlternateIndex
from catnip.catalog_path import CatalogPath
from catnip.labels import KsdsLabel
from jackal.cobol_step import (
    DEFAULT_PROGRAM_STEP_BUDGET,
    CompiledProgram,
    run_cobol_step,
)
from jackal.file_definitions import program_files_of
from jackal.catalog import DatasetCatalog
from jackal.model import DD, StepRef
from jackal.results import Completed, ProgramResult
from litter.package import Package
from tests.covers import NotLanguageFeature, covers
from tests.model_build import allocated, dd, disp, program
from tests.package_build import compiled, package
from tests.system_build import job_catalog, system, upload


def _ebcdic(text: bytes) -> bytes:
    return bytes(EbcdicTable.ascii_to_ebcdic(text))


@pytest.fixture(autouse=True)
def _require_bridge(bridge_jar):
    """Enforce PROLEAP_BRIDGE_JAR."""


@pytest.fixture(scope="module")
def packaged(tmp_path_factory: pytest.TempPathFactory, bridge_jar: str) -> Package:
    return package(
        tmp_path_factory.mktemp("package"), bridge_jar, ("ALTREAD", "ALTLOAD", "KEYCHK")
    )


_BASE = _ebcdic(b"001BBBxx002AAAyy003AAAzz")


def _path_catalog(tmp_path: Path) -> DatasetCatalog:
    upload(tmp_path, "J.KSDS", _BASE, KsdsLabel(8, 0, 3))
    system(tmp_path).define_aix(AlternateIndex("J.AIX", "J.KSDS", 3, 3, False))
    system(tmp_path).define_path(CatalogPath("J.PATH", "J.AIX"))
    return job_catalog(tmp_path)


def _compiled(packaged: Package, name: str) -> CompiledProgram:
    return compiled(packaged, name)


def _read_back(compiled: CompiledProgram, path: Path) -> CompiledProgram:
    codec = LinkedCodec(IrCodec())
    codec.write(compiled.linked, path)
    linked = codec.read(path)
    return CompiledProgram(linked, compiled.entry, program_files_of(linked))


def _ran(
    cat: DatasetCatalog, packaged: Package, name: str, dds: tuple[DD[StepRef], ...]
) -> ProgramResult:
    return _ran_compiled(cat, _compiled(packaged, name), name, dds)


def _ran_compiled(
    cat: DatasetCatalog,
    compiled: CompiledProgram,
    name: str,
    dds: tuple[DD[StepRef], ...],
) -> ProgramResult:
    step = program("S1", name, dds)
    return run_cobol_step(
        step,
        compiled,
        allocated(step, cat),
        cat.workdir,
        budget=DEFAULT_PROGRAM_STEP_BUDGET,
        relabeller=cat,
        builtins=core_builtins(),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_program_reads_a_cluster_through_its_path(tmp_path, packaged):
    cat = _path_catalog(tmp_path)
    rc = _ran(
        cat,
        packaged,
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
    tmp_path, packaged
):
    cat = _path_catalog(tmp_path)
    rc = _ran(cat, packaged, "ALTLOAD", (dd("XREFDD", "J.PATH", disp("SHR")),))

    assert rc == Completed(37)
    assert system(tmp_path).lookup("J.KSDS").path.read_bytes() == _BASE


@pytest.mark.parametrize(
    ("dsn", "messages"),
    [
        (
            "J.KSDS",
            [
                "J.KSDS: LRECL: declared 8, FD 9",
                "J.KSDS: key offset: declared 0, FD 3",
            ],
        ),
        ("J.PATH", ["J.PATH: LRECL: declared 8, FD 9"]),
    ],
)
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_an_fd_that_contradicts_a_keyed_label_gets_status_39_and_logs_each_field(
    tmp_path, packaged, caplog, dsn, messages
):
    cat = _path_catalog(tmp_path)
    compiled = _compiled(packaged, "KEYCHK")
    read_back = _read_back(compiled, tmp_path / "KEYCHK.linked.json")
    with caplog.at_level(logging.WARNING, logger="jackal.cobol_files"):
        rc = _ran_compiled(cat, read_back, "KEYCHK", (dd("XREFDD", dsn, disp("SHR")),))

    assert read_back.files == compiled.files
    assert rc == Completed(39)
    assert [
        r.getMessage() for r in caplog.records if r.name == "jackal.cobol_files"
    ] == messages
