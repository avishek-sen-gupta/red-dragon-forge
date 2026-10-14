"""CardDemo's data declaration: every dataset agrees with its copybook and its file, and installs into a system that runs CardDemo's jobs."""

from __future__ import annotations

from pathlib import Path

from catnip.dataset import Dataset
from catnip.declaration import Declaration, load_declaration
from catnip.install import install
from catnip.labels import KsdsLabel, PathView, SequentialLabel
from catnip.system_catalog import SystemCatalog
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.data_layout import record_length
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.parser import parse_jcl
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.results import Completed
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy

_FORGE_ROOT = Path(__file__).parents[2]
_DECLARATION = _FORGE_ROOT / "config" / "carddemo" / "data.toml"

_COPYBOOKS: dict[str, str] = {
    "AWS.M2.CARDDEMO.USRSEC.PS": "CSUSR01Y",
    "AWS.M2.CARDDEMO.ACCTDATA.PS": "CVACT01Y",
    "AWS.M2.CARDDEMO.CARDDATA.PS": "CVACT02Y",
    "AWS.M2.CARDDEMO.CUSTDATA.PS": "CVCUS01Y",
    "AWS.M2.CARDDEMO.CARDXREF.PS": "CVACT03Y",
    "AWS.M2.CARDDEMO.DALYTRAN.PS.INIT": "CVTRA06Y",
    "AWS.M2.CARDDEMO.DALYTRAN.PS": "CVTRA06Y",
    "AWS.M2.CARDDEMO.DISCGRP.PS": "CVTRA02Y",
    "AWS.M2.CARDDEMO.TRANCATG.PS": "CVTRA04Y",
    "AWS.M2.CARDDEMO.TRANTYPE.PS": "CVTRA03Y",
    "AWS.M2.CARDDEMO.TCATBALF.PS": "CVTRA01Y",
}

UNDECLARED: dict[str, str] = {
    "AWS.M2.CARDDEMO.ACCDATA.PS": (
        "not in the README's table; a byte-identical copy of ACCTDATA.PS that no job reads"
    ),
    "AWS.M2.CARDDEMO.EXPORT.DATA.PS": (
        "not in the README's table and no job reads it; CBEXPORT/CBIMPORT use the "
        "AWS.M2.CARDDEMO.EXPORT.DATA KSDS, which CBEXPORT defines"
    ),
}


def _declaration(tmp_path: Path) -> Declaration:
    copy = tmp_path / "data.toml"
    copy.write_text(_DECLARATION.read_text().replace("${FORGE_ROOT}", str(_FORGE_ROOT)))
    return load_declaration(copy)


def _copybook_length(parser: ProLeapCobolParser, copybook: str) -> int:
    source = (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. SZ.\n"
        "       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
        f"       COPY {copybook}.\n       PROCEDURE DIVISION.\n           GOBACK.\n"
    )
    records = parser.parse(source.encode()).data_fields
    return record_length(records[0])


def _records(data: bytes, lrecl: int) -> list[bytes]:
    return [data[at : at + lrecl] for at in range(0, len(data), lrecl)]


def test_every_declared_carddemo_dataset_agrees_with_its_copybook_and_its_file(
    tmp_path: Path, carddemo_home: Path, bridge_jar: str
) -> None:
    parser = ProLeapCobolParser(
        RealSubprocessRunner(), bridge_jar, copybook_dirs=[carddemo_home / "cpy"]
    )
    declaration = _declaration(tmp_path)
    data = carddemo_home / "data" / "EBCDIC"
    seeded = [(s.dsn, s.seed, s.lrecl) for s in declaration.sequential] + [
        (k.dsn, k.seed, k.lrecl) for k in declaration.ksds if isinstance(k.seed, Path)
    ]
    checks = [
        (
            dsn,
            _copybook_length(parser, _COPYBOOKS[seed.name]) - lrecl,
            seed.stat().st_size % lrecl,
        )
        for dsn, seed, lrecl in seeded
    ]
    declared = {seed.name for _, seed, _ in seeded} | set(UNDECLARED)
    data_files = sorted(p.name for p in data.iterdir() if not p.name.startswith("."))
    assert (
        declaration.data_dir.resolve(),
        [s.dsn for s in declaration.sequential],
        len(seeded),
        checks,
        data_files,
    ) == (
        data.resolve(),
        list(_COPYBOOKS),
        len(declaration.sequential) + len(declaration.ksds),
        [(dsn, 0, 0) for dsn, _, _ in seeded],
        sorted(declared),
    )


def test_an_installed_carddemo_system_holds_each_dataset_and_runs_acctfile(
    tmp_path: Path, carddemo_home: Path, bridge_jar: str
) -> None:
    declaration = _declaration(tmp_path)
    root = tmp_path / "system"
    install(declaration, SystemCatalog(root))
    system = SystemCatalog(root)
    xref = "AWS.M2.CARDDEMO.CARDXREF.VSAM.KSDS"
    xref_bytes = (root / "datasets" / xref).read_bytes()
    runner = JobRunner(
        source_dir=carddemo_home / "cbl",
        bridge_jar=bridge_jar,
        system=system,
        copybook_dir=carddemo_home / "cpy",
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
    )
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    result = runner.run(
        parse_jcl((carddemo_home / "jcl" / "ACCTFILE.jcl").read_text()), scratch
    )
    ksds = "AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS"
    sequential = declaration.sequential
    data = carddemo_home / "data" / "EBCDIC"
    xref_source = (data / "AWS.M2.CARDDEMO.CARDXREF.PS").read_bytes()
    assert (
        [system.lookup(s.dsn) for s in sequential],
        [(root / "datasets" / s.dsn).read_bytes() for s in sequential],
        xref_bytes,
        system.lookup("AWS.M2.CARDDEMO.CARDXREF.VSAM.AIX.PATH").label,
        [s.outcome for s in result.steps],
        SystemCatalog(root).lookup(ksds),
    ) == (
        [
            Dataset(s.dsn, root / "datasets" / s.dsn, SequentialLabel(s.recfm, s.lrecl))
            for s in sequential
        ],
        [(data / s.dsn).read_bytes() for s in sequential],
        b"".join(sorted(_records(xref_source, 50), key=lambda r: r[:16])),
        PathView(KsdsLabel(50, 0, 16), 25, 11, False),
        [Completed(0), Completed(0), Completed(0)],
        Dataset(ksds, root / "datasets" / ksds, KsdsLabel(300, 0, 11)),
    )
