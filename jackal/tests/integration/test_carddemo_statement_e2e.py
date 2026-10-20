"""CardDemo's statement step: CBSTM03A, entered by PGM=, with CBSTM03B linked beside it to read the files it declares."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from catnip.dataset import Dataset
from catnip.declaration import Declaration, KsdsEntry
from catnip.install import install
from catnip.labels import RecordFormat, SequentialLabel
from interpreter.vm.builtins import core_builtins
from jackal.file_definitions import program_files_of
from jackal.jcl.parser import parse_jcl
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.results import Completed
from jackal.runner import JobRunner
from jackal.unknown_return_code import RaiseUnknownReturnCode
from jackal.unresolved import RaiseErrorStrategy
from litter.package import Package
from tests.covers import NotLanguageFeature, covers
from tests.package_build import package
from tests.system_build import job_catalog, system

_DATA = "data/EBCDIC/AWS.M2.CARDDEMO"
_TRAN_LRECL = 350
_CARD_IN_TRAN = slice(262, 278)
_SPACE = b"\x40"
_BUDGET = 2_000_000

_JCL = """\
//CREASTMT JOB 1
//STEP040  EXEC PGM=CBSTM03A
//TRNXFILE DD  DISP=SHR,DSN=J.TRXFL.KSDS
//XREFFILE DD  DISP=SHR,DSN=J.CARDXREF.KSDS
//ACCTFILE DD  DISP=SHR,DSN=J.ACCTDATA.KSDS
//CUSTFILE DD  DISP=SHR,DSN=J.CUSTDATA.KSDS
//STMTFILE DD DISP=(NEW,CATLG,DELETE),DCB=(LRECL=80,RECFM=FB),
//         DSN=J.STATEMNT.PS
//HTMLFILE DD  DISP=(NEW,CATLG,DELETE),DCB=(LRECL=100,RECFM=FB),
//         DSN=J.STATEMNT.HTML
"""


def _records(data: bytes, lrecl: int) -> tuple[bytes, ...]:
    return tuple(data[i : i + lrecl] for i in range(0, len(data), lrecl))


def _statement_transactions(transactions: bytes, card: bytes) -> bytes:
    return b"".join(
        (r[_CARD_IN_TRAN] + r[:262] + r[278:328]).ljust(_TRAN_LRECL, _SPACE)
        for r in _records(transactions, _TRAN_LRECL)
        if r[_CARD_IN_TRAN] == card
    )


def _seeded(tmp_path: Path, carddemo_home: Path) -> None:
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    xref = _records((carddemo_home / f"{_DATA}.CARDXREF.PS").read_bytes(), 50)[0]
    (seeds / "XREF").write_bytes(xref)
    (seeds / "TRXFL").write_bytes(
        _statement_transactions(
            (carddemo_home / f"{_DATA}.DALYTRAN.PS").read_bytes(), xref[:16]
        )
    )
    shutil.copy(carddemo_home / f"{_DATA}.ACCTDATA.PS", seeds / "ACCT")
    shutil.copy(carddemo_home / f"{_DATA}.CUSTDATA.PS", seeds / "CUST")
    install(
        Declaration(
            seeds,
            (),
            (
                KsdsEntry("J.TRXFL.KSDS", seeds / "TRXFL", _TRAN_LRECL, 0, 32, ()),
                KsdsEntry("J.CARDXREF.KSDS", seeds / "XREF", 50, 0, 16, ()),
                KsdsEntry("J.ACCTDATA.KSDS", seeds / "ACCT", 300, 0, 11, ()),
                KsdsEntry("J.CUSTDATA.KSDS", seeds / "CUST", 500, 0, 9, ()),
            ),
            (),
        ),
        system(tmp_path),
    )


def _sources(tmp_path: Path, carddemo_home: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    for name in ("CBSTM03A", "CBSTM03B"):
        shutil.copy(carddemo_home / "cbl" / f"{name}.CBL", src / f"{name}.cbl")
    return src


def _package(tmp_path: Path, carddemo_home: Path, bridge_jar: str) -> Package:
    return package(
        tmp_path / "package",
        bridge_jar,
        ("CBSTM03A", "CBSTM03B"),
        _sources(tmp_path, carddemo_home),
        (carddemo_home / "cpy",),
    )


@pytest.mark.carddemo_e2e
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_each_statement_program_declares_its_own_files(
    tmp_path: Path, carddemo_home: Path, bridge_jar: str
) -> None:
    image = _package(tmp_path, carddemo_home, bridge_jar).image

    assert sorted(
        (f.program, f.entry.file_name, f.entry.assign_to)
        for f in program_files_of(image)
    ) == [
        ("CBSTM03A", "HTML-FILE", "HTMLFILE"),
        ("CBSTM03A", "STMT-FILE", "STMTFILE"),
        ("CBSTM03B", "ACCT-FILE", "ACCTFILE"),
        ("CBSTM03B", "CUST-FILE", "CUSTFILE"),
        ("CBSTM03B", "TRNX-FILE", "TRNXFILE"),
        ("CBSTM03B", "XREF-FILE", "XREFFILE"),
    ]


@pytest.mark.carddemo_e2e
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_the_statement_step_writes_the_statements(
    tmp_path: Path, carddemo_home: Path, bridge_jar: str
) -> None:
    _seeded(tmp_path, carddemo_home)
    runner = JobRunner(
        package=_package(tmp_path, carddemo_home, bridge_jar),
        system=system(tmp_path),
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        unknown_return_code=RaiseUnknownReturnCode(),
        program_step_budget=_BUDGET,
        builtins=core_builtins(),
    )

    result = runner.run_job(parse_jcl(_JCL), job_catalog(tmp_path))
    reloaded = system(tmp_path)
    statements, html = reloaded.lookup("J.STATEMNT.PS"), reloaded.lookup(
        "J.STATEMNT.HTML"
    )

    assert (
        [s.outcome for s in result.steps],
        statements.label if isinstance(statements, Dataset) else statements,
        html.label if isinstance(html, Dataset) else html,
    ) == (
        [Completed(0)],
        SequentialLabel(RecordFormat.FB, 80),
        SequentialLabel(RecordFormat.FB, 100),
    )
