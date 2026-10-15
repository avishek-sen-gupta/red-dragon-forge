"""Integration tests: DSN=*.ddname names the dataset of an earlier DD of the same step."""

from __future__ import annotations

from pathlib import Path

import pytest
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.model import DdName, StepDd
from jackal.results import Completed
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy, UnresolvedReference
from tests.covers import NotLanguageFeature, covers
from tests.package_build import EMPTY
from tests.model_build import dd, disp, job, program
from tests.system_build import job_catalog, scratch, system


def _runner(tmp_path: Path) -> JobRunner:
    return JobRunner(
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        package=EMPTY,
        system=system(tmp_path),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_same_step_referback_allocates_the_earlier_dds_dataset(tmp_path):
    """The step's second DD reaches the dataset its first DD created; a name no
    earlier DD of the step has is an unresolved reference, rejected before any
    step runs."""
    made = job(
        "J",
        (
            program(
                "S1",
                "IEFBR14",
                (
                    dd("NEW", "T.MADE", disp("NEW", "CATLG")),
                    dd("AGAIN", StepDd(DdName("NEW")), disp("SHR")),
                ),
            ),
        ),
    )
    dangling = job(
        "J",
        (program("S1", "IEFBR14", (dd("LOST", StepDd(DdName("NOPE")), disp("SHR")),)),),
    )
    result = _runner(tmp_path).run(made, scratch=scratch(tmp_path))
    assert result.steps[0].outcome == Completed(0)
    assert job_catalog(tmp_path).resolve("T.MADE").dsn == "T.MADE"
    with pytest.raises(UnresolvedReference):
        _runner(tmp_path).run(dangling, scratch=scratch(tmp_path))
