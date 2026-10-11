"""The runner allocates every DD before a program runs and disposes after it."""

from pathlib import Path

import pytest
from interpreter.cobol.ebcdic_table import EbcdicTable
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.bridge_parser import JclBridgeParser, JclSubprocessRunner
from jackal.labels import RecordFormat, SequentialLabel
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
from jackal.system_catalog import NotCataloged
from jackal.unresolved import RaiseErrorStrategy
from tests.covers import NotLanguageFeature, covers
from tests.system_build import job_catalog, system

CBL = Path(__file__).parent / "fixtures" / "cbl"


@pytest.fixture(autouse=True)
def _require(bridge_jar, jcl_bridge_jar):
    """Both JARs are required for every test in this module."""


def _ebcdic(text: str) -> bytes:
    return bytes(EbcdicTable.ascii_to_ebcdic(text.encode("ascii")))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_cobol_step_with_or_without_parm_reads_in_stream_cards_and_a_dummy_input(
    tmp_path: Path, bridge_jar: str, jcl_bridge_jar: str
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
        source_dir=CBL,
        bridge_jar=bridge_jar,
        system=system(tmp_path),
        copybook_dir=tmp_path,
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
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
    tmp_path: Path, bridge_jar: str, jcl_bridge_jar: str
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
        source_dir=CBL,
        bridge_jar=bridge_jar,
        system=system(tmp_path),
        copybook_dir=tmp_path,
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
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
    tmp_path: Path, bridge_jar: str, jcl_bridge_jar: str
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
        source_dir=CBL,
        bridge_jar=bridge_jar,
        system=system(tmp_path),
        copybook_dir=tmp_path,
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=2_000,
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


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_cobol_open_labels_a_new_dataset_and_fails_status_39_on_a_conflicting_one(
    tmp_path: Path, bridge_jar: str, jcl_bridge_jar: str
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
    )
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    catalog = job_catalog(tmp_path)
    runner = JobRunner(
        source_dir=CBL,
        bridge_jar=bridge_jar,
        system=system(tmp_path),
        copybook_dir=tmp_path,
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
    )
    result = runner.run_job(job, catalog)
    reloaded = system(tmp_path)
    assert (
        [s.outcome for s in result.steps],
        reloaded.lookup("J.FIX").label,
        reloaded.lookup("J.VAR").label,
    ) == (
        [Completed(0), Completed(0), Completed(39)],
        SequentialLabel(RecordFormat.F, 80),
        SequentialLabel(RecordFormat.V, 104),
    )
