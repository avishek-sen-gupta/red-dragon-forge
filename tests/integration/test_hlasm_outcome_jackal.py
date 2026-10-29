"""A jackal step whose program is HLASM completes with its R15 or abends with its code."""

from __future__ import annotations

from pathlib import Path

from catnip.system_catalog import SystemCatalog
from infrastructure.zos.abend.user_abend import UserAbend
from interpreter.vm.builtins import core_builtins
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.parser import parse_jcl
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.results import Abended, Completed, StepOutcome
from jackal.runner import JobRunner
from jackal.unknown_return_code import RaiseUnknownReturnCode
from jackal.unresolved import RaiseErrorStrategy
from litter.open import open_package

from tests.integration.test_hlasm_outcome_plain import built_outcome_package


def test_hlasm_steps_report_their_return_code_and_their_abend(tmp_path: Path) -> None:
    runner = JobRunner(
        package=open_package(
            built_outcome_package(tmp_path, (), ("RCEIGHT", "ABEND42"))
        ),
        system=SystemCatalog(tmp_path / "system"),
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        unknown_return_code=RaiseUnknownReturnCode(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        builtins=core_builtins(),
    )
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    jcl = "//J JOB 1\n//S1 EXEC PGM=RCEIGHT\n//S2 EXEC PGM=ABEND42\n"

    outcomes: list[StepOutcome] = [
        s.outcome for s in runner.run(parse_jcl(jcl), scratch).steps
    ]

    assert outcomes == [Completed(8), Abended(UserAbend(42))]
