"""Two programs in one image declaring the same SELECT name each open their own DD with their own FD."""

from pathlib import Path

import pytest
from catnip.labels import RecordFormat, SequentialLabel
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.parser import parse_jcl
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.results import Completed
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy
from tests.covers import NotLanguageFeature, covers
from tests.package_build import package
from tests.system_build import job_catalog, system


def _writer(program: str, ddname: str, length: int) -> str:
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. {program}.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCTFILE ASSIGN TO {ddname}
                  ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  ACCTFILE RECORDING MODE IS F.
       01  ACCT-REC  PIC X({length}).
       PROCEDURE DIVISION.
           OPEN OUTPUT ACCTFILE.
           MOVE 'WRITTEN BY {program}' TO ACCT-REC.
           WRITE ACCT-REC.
           CLOSE ACCTFILE.
           GOBACK.
"""


_JCL = (
    "//J JOB 1\n"
    "//S1 EXEC PGM=ACCTA\n"
    "//ADDA DD DSN=J.A,DISP=(NEW,CATLG)\n"
    "//S2 EXEC PGM=ACCTB\n"
    "//BDDB DD DSN=J.B,DISP=(NEW,CATLG)\n"
)


@pytest.mark.parametrize("linked", [("ACCTA", "ACCTB"), ("ACCTB", "ACCTA")])
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_each_program_opens_its_own_dd_and_labels_it_from_its_own_fd(
    tmp_path: Path, bridge_jar: str, linked: tuple[str, str]
) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "ACCTA.cbl").write_text(_writer("ACCTA", "ADDA", 80))
    (src / "ACCTB.cbl").write_text(_writer("ACCTB", "BDDB", 120))
    runner = JobRunner(
        package=package(tmp_path / "package", bridge_jar, linked, src),
        system=system(tmp_path),
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
    )

    result = runner.run_job(parse_jcl(_JCL), job_catalog(tmp_path))
    reloaded = system(tmp_path)
    a, b = reloaded.lookup("J.A"), reloaded.lookup("J.B")

    assert (
        [s.outcome for s in result.steps],
        (a.label, a.path.read_bytes()),
        (b.label, b.path.read_bytes()),
    ) == (
        [Completed(0), Completed(0)],
        (
            SequentialLabel(RecordFormat.F, 80),
            "WRITTEN BY ACCTA".ljust(80).encode("cp037"),
        ),
        (
            SequentialLabel(RecordFormat.F, 120),
            "WRITTEN BY ACCTB".ljust(120).encode("cp037"),
        ),
    )
