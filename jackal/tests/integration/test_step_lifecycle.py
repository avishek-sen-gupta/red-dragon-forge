"""The runner allocates every DD before a program runs and disposes after it."""

import logging
from pathlib import Path

import pytest
from catnip.labels import RecordFormat, SequentialLabel
from catnip.system_catalog import NotCataloged
from interpreter.encoding.ebcdic_table import EbcdicTable
from interpreter.vm.builtins import core_builtins
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.bridge_parser import JclBridgeParser, JclSubprocessRunner
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.results import (
    Abended,
    AfterAbend,
    Completed,
    Flushed,
    JobAbended,
    SystemAbend,
)
from jackal.runner import JobRunner
from jackal.unknown_return_code import RaiseUnknownReturnCode
from jackal.unresolved import RaiseErrorStrategy
from litter.package import Package
from tests.covers import NotLanguageFeature, covers
from tests.package_build import package
from tests.system_build import job_catalog, system


@pytest.fixture(scope="module")
def packaged(tmp_path_factory: pytest.TempPathFactory, bridge_jar: str) -> Package:
    return package(
        tmp_path_factory.mktemp("package"),
        bridge_jar,
        ("CARDCOPY", "RUNAWAY", "FIXWRITE", "VARWRITE", "SHORTRD", "VARREAD"),
    )


@pytest.fixture(autouse=True)
def _require(bridge_jar, jcl_bridge_jar):
    """Both JARs are required for every test in this module."""


def _ebcdic(text: str) -> bytes:
    return bytes(EbcdicTable.ascii_to_ebcdic(text.encode("ascii")))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_cobol_step_with_or_without_parm_reads_in_stream_cards_and_a_dummy_input(
    tmp_path: Path, packaged: Package, jcl_bridge_jar: str
) -> None:
    jcl = (
        "//J JOB 1\n"
        "//S1 EXEC PGM=CARDCOPY,PARM='X'\n"
        "//SYSIN DD *\n"
        " HELLO\n"
        " WORLD\n"
        "/*\n"
        "//OUTDD DD DSN=J.CARDS,DISP=(NEW,CATLG)\n"
        "//S2 EXEC PGM=CARDCOPY\n"
        "//STEPLIB DD DSN=PROD.LOADLIB,DISP=SHR\n"
        "//SYSIN DD DUMMY\n"
        "//OUTDD DD DSN=J.EMPTY,DISP=(NEW,CATLG)\n"
    )
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    catalog = job_catalog(tmp_path)
    runner = JobRunner(
        package=packaged,
        system=system(tmp_path),
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        unknown_return_code=RaiseUnknownReturnCode(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        builtins=core_builtins(),
    )
    result = runner.run_job(job, catalog)
    assert (
        [s.outcome for s in result.steps],
        catalog.resolve("J.CARDS").path.read_bytes(),
        catalog.resolve("J.EMPTY").path.read_bytes(),
    ) == (
        [Completed(0), Completed(0)],
        _ebcdic(" HELLO".ljust(80) + " WORLD".ljust(80)),
        b"",
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_cobol_step_writing_a_mod_dataset_appends_to_it(
    tmp_path: Path, packaged: Package, jcl_bridge_jar: str
) -> None:
    jcl = (
        "//J JOB 1\n"
        "//S1 EXEC PGM=CARDCOPY\n"
        "//SYSIN DD *\n"
        " FIRST\n"
        "/*\n"
        "//OUTDD DD DSN=J.LOG,DISP=(NEW,CATLG)\n"
        "//S2 EXEC PGM=CARDCOPY\n"
        "//SYSIN DD *\n"
        " SECOND\n"
        "/*\n"
        "//OUTDD DD DSN=J.LOG,DISP=MOD\n"
    )
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    catalog = job_catalog(tmp_path)
    runner = JobRunner(
        package=packaged,
        system=system(tmp_path),
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        unknown_return_code=RaiseUnknownReturnCode(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        builtins=core_builtins(),
    )
    result = runner.run_job(job, catalog)
    assert (
        [s.outcome for s in result.steps],
        catalog.resolve("J.LOG").path.read_bytes(),
    ) == (
        [Completed(0), Completed(0)],
        _ebcdic(" FIRST".ljust(80) + " SECOND".ljust(80)),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_cobol_program_that_never_ends_abends_s322_when_its_budget_runs_out(
    tmp_path: Path, packaged: Package, jcl_bridge_jar: str
) -> None:
    jcl = (
        "//J JOB 1\n"
        "//S1 EXEC PGM=RUNAWAY\n"
        "//OUTDD DD DSN=J.PARTIAL,DISP=(NEW,CATLG,DELETE)\n"
        "//S2 EXEC PGM=IEFBR14\n"
    )
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    catalog = job_catalog(tmp_path)
    runner = JobRunner(
        package=packaged,
        system=system(tmp_path),
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        unknown_return_code=RaiseUnknownReturnCode(),
        program_step_budget=2_000,
        builtins=core_builtins(),
    )
    result = runner.run_job(job, catalog)
    s1, s322 = result.steps[0].step, SystemAbend(0x322)
    assert (
        [s.outcome for s in result.steps],
        result.outcome,
        catalog.resolve("J.PARTIAL"),
    ) == (
        [Abended(s322), Flushed(AfterAbend(s1))],
        JobAbended(s1, s322),
        NotCataloged(),
    )


VARYING = "VARYING".ljust(100).encode("cp037")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_cobol_open_labels_a_new_dataset_and_fails_status_39_on_a_conflicting_one(
    tmp_path: Path,
    packaged: Package,
    jcl_bridge_jar: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Enterprise COBOL 6.4 Programming Guide, ch. 9: the program's attributes are
    used for a new file; a mismatch in record format or length with an existing
    one fails the OPEN with file status 39."""
    jcl = (
        "//J JOB 1\n"
        "//S1 EXEC PGM=FIXWRITE\n"
        "//OUTDD DD DSN=J.FIX,DISP=(NEW,CATLG)\n"
        "//S2 EXEC PGM=VARWRITE\n"
        "//OUTDD DD DSN=J.VAR,DISP=(NEW,CATLG)\n"
        "//S3 EXEC PGM=SHORTRD\n"
        "//INDD DD DSN=J.FIX,DISP=SHR\n"
        "//S4 EXEC PGM=VARREAD\n"
        "//INDD DD DSN=J.VAR,DISP=SHR\n"
        "//OUTDD DD DSN=J.COPY,DISP=(NEW,CATLG)\n"
    )
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    catalog = job_catalog(tmp_path)
    runner = JobRunner(
        package=packaged,
        system=system(tmp_path),
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        unknown_return_code=RaiseUnknownReturnCode(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        builtins=core_builtins(),
    )
    with caplog.at_level(logging.WARNING, logger="jackal.cobol_files"):
        result = runner.run_job(job, catalog)
    reloaded = system(tmp_path)
    var, copy = reloaded.lookup("J.VAR"), reloaded.lookup("J.COPY")
    assert (
        [s.outcome for s in result.steps],
        reloaded.lookup("J.FIX").label,
        (var.label, var.path.read_bytes()),
        (copy.label, copy.path.read_bytes()),
    ) == (
        [Completed(0), Completed(0), Completed(39), Completed(0)],
        SequentialLabel(RecordFormat.F, 80),
        (SequentialLabel(RecordFormat.V, 104), b"\x00\x68\x00\x00" + VARYING),
        (SequentialLabel(RecordFormat.F, 100), VARYING),
    )
    assert [
        r.getMessage() for r in caplog.records if r.name == "jackal.cobol_files"
    ] == ["J.FIX: LRECL: declared 80, FD 50"]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_cobol_step_writing_to_dummy_or_nullfile_keeps_nothing(
    tmp_path: Path, packaged: Package, jcl_bridge_jar: str
) -> None:
    jcl = (
        "//J JOB 1\n"
        "//S1 EXEC PGM=FIXWRITE\n"
        "//OUTDD DD DUMMY\n"
        "//S2 EXEC PGM=FIXWRITE\n"
        "//OUTDD DD DSN=NULLFILE\n"
    )
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    runner = JobRunner(
        package=packaged,
        system=system(tmp_path),
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        unknown_return_code=RaiseUnknownReturnCode(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        builtins=core_builtins(),
    )
    result = runner.run_job(job, job_catalog(tmp_path))
    kept = sorted(p.name for p in tmp_path.rglob("*") if p.is_file())
    assert ([s.outcome for s in result.steps], kept) == (
        [Completed(0), Completed(0)],
        [],
    )
