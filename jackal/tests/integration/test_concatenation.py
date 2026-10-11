"""A concatenated DD reads as one dataset, member after member; it cannot be written.

Sources: z/OS 3.1 MVS JCL Reference, "Concatenating data sets", pp. 91-92; z/OS 3.1
DFSMS Using Data Sets, "Concatenating Data Sets Sequentially", pp. 369-370. See
docs/records/design/2026-10-12-jackal-concatenation.md.
"""

from pathlib import Path

import pytest
from interpreter.cobol.ebcdic_table import EbcdicTable
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.bridge_parser import JclBridgeParser, JclSubprocessRunner
from jackal.labels import RecordFormat, SequentialLabel
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.results import Completed
from jackal.runner import JobRunner
from jackal.system_catalog import NotCataloged
from jackal.unresolved import RaiseErrorStrategy
from tests.covers import NotLanguageFeature, covers
from tests.system_build import job_catalog, system, upload

CBL = Path(__file__).parent / "fixtures" / "cbl"
FB5 = SequentialLabel(RecordFormat.FB, 5)


@pytest.fixture(autouse=True)
def _require(bridge_jar, jcl_bridge_jar):
    """Both JARs are required for every test in this module."""


def _ebcdic(text: bytes) -> bytes:
    return bytes(EbcdicTable.ascii_to_ebcdic(text))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_program_reads_a_concatenation_member_by_member_and_cannot_write_one(
    tmp_path: Path, bridge_jar: str, jcl_bridge_jar: str
) -> None:
    upload(tmp_path, "J.IN1", _ebcdic(b"applekiwis"), FB5)
    upload(tmp_path, "J.IN2", _ebcdic(b"mango"), FB5)
    jcl = (
        "//J JOB 1\n"
        "//S1 EXEC PGM=COPYUP\n"
        "//INDD DD DSN=J.IN1,DISP=SHR\n"
        "//     DD DSN=J.IN2,DISP=(OLD,DELETE)\n"
        "//OUTDD DD DSN=J.OUT,DISP=(NEW,CATLG)\n"
        "//S2 EXEC PGM=CATWRITE\n"
        "//OUTDD DD DSN=J.IN1,DISP=SHR\n"
        "//      DD DSN=J.OUT,DISP=SHR\n"
    )
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
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
    result = runner.run_job(job, job_catalog(tmp_path))
    reloaded = system(tmp_path)
    assert (
        [s.outcome for s in result.steps],
        reloaded.lookup("J.OUT").path.read_bytes(),
        reloaded.lookup("J.IN2"),
        reloaded.lookup("J.IN1").path.read_bytes(),
    ) == (
        [Completed(0), Completed(37)],
        _ebcdic(b"APPLEKIWISMANGO"),
        NotCataloged(),
        _ebcdic(b"applekiwis"),
    )
