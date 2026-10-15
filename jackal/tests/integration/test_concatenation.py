"""A concatenated DD reads as one dataset, member after member; it cannot be written.

Sources: z/OS 3.1 MVS JCL Reference, "Concatenating data sets", pp. 91-92; z/OS 3.1
DFSMS Using Data Sets, "Concatenating Data Sets Sequentially", pp. 369-370. See
docs/records/design/2026-10-12-jackal-concatenation.md.
"""

import logging
from pathlib import Path

import pytest
from catnip.labels import RecordFormat, SequentialLabel
from catnip.system_catalog import NotCataloged
from interpreter.cobol.ebcdic_table import EbcdicTable
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.bridge_parser import JclBridgeParser, JclSubprocessRunner
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.results import Completed
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy
from tests.covers import NotLanguageFeature, covers
from tests.package_build import package
from tests.system_build import job_catalog, system, upload

FB5 = SequentialLabel(RecordFormat.FB, 5)


@pytest.fixture(autouse=True)
def _require(bridge_jar, jcl_bridge_jar):
    """Both JARs are required for every test in this module."""


def _ebcdic(text: bytes) -> bytes:
    return bytes(EbcdicTable.ascii_to_ebcdic(text))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_concatenation_reads_member_by_member_cannot_be_written_and_logs_a_conflicting_member(
    tmp_path: Path,
    bridge_jar: str,
    jcl_bridge_jar: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    upload(tmp_path, "J.IN1", _ebcdic(b"applekiwis"), FB5)
    upload(tmp_path, "J.IN2", _ebcdic(b"mango"), FB5)
    upload(tmp_path, "J.BAD6", _ebcdic(b"banana"), SequentialLabel(RecordFormat.FB, 6))
    upload(tmp_path, "J.BAD4", _ebcdic(b"pear"), SequentialLabel(RecordFormat.FB, 4))
    jcl = (
        "//J JOB 1\n"
        "//S1 EXEC PGM=COPYUP\n"
        "//INDD DD DSN=J.IN1,DISP=SHR\n"
        "//     DD DSN=J.IN2,DISP=(OLD,DELETE)\n"
        "//OUTDD DD DSN=J.OUT,DISP=(NEW,CATLG)\n"
        "//S2 EXEC PGM=CATWRITE\n"
        "//OUTDD DD DSN=J.IN1,DISP=SHR\n"
        "//      DD DSN=J.OUT,DISP=SHR\n"
        "//S3 EXEC PGM=CONCHK\n"
        "//INDD DD DSN=J.IN1,DISP=SHR\n"
        "//     DD DSN=J.BAD6,DISP=SHR\n"
        "//S4 EXEC PGM=CONCHK\n"
        "//INDD DD DSN=J.BAD4,DISP=SHR\n"
        "//     DD DSN=J.IN1,DISP=SHR\n"
    )
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    runner = JobRunner(
        package=package(tmp_path / "package", ("COPYUP", "CATWRITE", "CONCHK")),
        system=system(tmp_path),
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
    )
    with caplog.at_level(logging.WARNING, logger="jackal.cobol_files"):
        result = runner.run_job(job, job_catalog(tmp_path))
    reloaded = system(tmp_path)
    assert (
        [s.outcome for s in result.steps],
        reloaded.lookup("J.OUT").path.read_bytes(),
        reloaded.lookup("J.IN2"),
        reloaded.lookup("J.IN1").path.read_bytes(),
    ) == (
        [Completed(0), Completed(37), Completed(39), Completed(39)],
        _ebcdic(b"APPLEKIWISMANGO"),
        NotCataloged(),
        _ebcdic(b"applekiwis"),
    )
    assert [
        r.getMessage() for r in caplog.records if r.name == "jackal.cobol_files"
    ] == ["J.BAD6: LRECL: declared 6, FD 5", "J.BAD4: LRECL: declared 4, FD 5"]
