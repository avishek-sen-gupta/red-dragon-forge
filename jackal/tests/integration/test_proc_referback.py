"""Integration test: a later step refers back into a DD of a called PROC's step (*.STEP.PROCSTEP.DD)."""

from pathlib import Path

import pytest
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.parser import parse_jcl
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.results import Completed
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy
from tests.covers import NotLanguageFeature, covers
from tests.package_build import EMPTY
from tests.system_build import job_catalog, scratch, system
from interpreter.vm.builtins import core_builtins


@pytest.fixture(autouse=True)
def _require(jcl_bridge_jar):
    """The JCL bridge JAR parses the job and the PROC."""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_step_receives_a_dataset_passed_by_a_procs_step(tmp_path: Path):
    """JCL Ref, DD DSNAME: *.stepname.procstepname.ddname names a DD in a step of
    the PROC that stepname called. The passed dataset is received there and
    cataloged; had the reference not resolved, it would have been deleted at job
    end as passed and never received."""
    procs = tmp_path / "procs"
    procs.mkdir()
    (procs / "MKPASS.prc").write_text(
        "//MKPASS PROC\n//P1 EXEC PGM=IEFBR14\n//OUT DD DSN=T.HANDED,DISP=(NEW,PASS)\n"
    )
    runner = JobRunner(
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        package=EMPTY,
        system=system(tmp_path),
        proclib_dirs=(procs,),
        builtins=core_builtins(),
    )
    jcl = (
        "//J JOB 1\n"
        "//S1 EXEC MKPASS\n"
        "//S2 EXEC PGM=IEFBR14\n"
        "//IN DD DSN=*.S1.P1.OUT,DISP=(OLD,CATLG)\n"
    )
    steps = runner.run(parse_jcl(jcl), scratch=scratch(tmp_path)).steps
    assert [s.outcome for s in steps] == [Completed(0), Completed(0)]
    assert job_catalog(tmp_path).resolve("T.HANDED").dsn == "T.HANDED"
