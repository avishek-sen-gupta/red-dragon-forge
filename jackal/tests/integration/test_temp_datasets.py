"""Integration tests: &&NAME temporary dataset lifecycle via JobRunner."""

from __future__ import annotations

from pathlib import Path

from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.missing_data import (
    LenientAllocation,
    MissingDataStrategy,
    StrictAllocation,
)
from jackal.missing_program import AbendMissingProgram
from jackal.model import (
    DD,
    CondOp,
    DdName,
    IfBlock,
    RcTest,
    StepName,
    StepRef,
    TempRef,
)
from jackal.results import AllocationError, AllocationFailed, Completed
from jackal.runner import JobRunner, UnsupportedStep
from jackal.unresolved import RaiseErrorStrategy
from tests.covers import NotLanguageFeature, covers
from tests.model_build import dd, disp, job, program, ref
from tests.system_build import scratch, system


def _pass_dd(name: str) -> DD[StepRef]:
    return dd("WRK", TempRef(name), disp("NEW", "PASS", "DELETE"))


def _old_pass_dd(name: str) -> DD[StepRef]:
    return dd("WRK", TempRef(name), disp("OLD", "PASS", "DELETE"))


def _old_delete_dd(name: str) -> DD[StepRef]:
    return dd("WRK", TempRef(name), disp("OLD", "DELETE", "DELETE"))


def _scratch_files(root: Path) -> list[str]:
    return sorted(p.name for p in (root / "scratch").iterdir())


def _runner(tmp_path, missing_data: MissingDataStrategy = StrictAllocation()):
    return JobRunner(
        unresolved=RaiseErrorStrategy(),
        missing_data=missing_data,
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        source_dir=tmp_path,
        bridge_jar="unused",
        system=system(tmp_path),
        copybook_dir=tmp_path,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_two_step_temp_dataset(tmp_path):
    """Step 1 creates &&TEMP (PASS); step 2 opens and deletes it."""
    j = job(
        "J",
        (
            program("S1", "IEFBR14", (_pass_dd("TEMP"),)),
            program("S2", "IEFBR14", (_old_delete_dd("TEMP"),)),
        ),
    )
    result = _runner(tmp_path).run(j, scratch=scratch(tmp_path))
    assert all(s.outcome == Completed(0) for s in result.steps)
    assert _scratch_files(tmp_path) == []


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_three_step_pass_chain(tmp_path):
    """Step 1 creates &&TEMP; step 2 reads+passes; step 3 deletes."""
    j = job(
        "J",
        (
            program("S1", "IEFBR14", (_pass_dd("TEMP"),)),
            program("S2", "IEFBR14", (_old_pass_dd("TEMP"),)),
            program("S3", "IEFBR14", (_old_delete_dd("TEMP"),)),
        ),
    )
    result = _runner(tmp_path).run(j, scratch=scratch(tmp_path))
    assert all(s.outcome == Completed(0) for s in result.steps)
    assert _scratch_files(tmp_path) == []


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_temp_never_created_fails_its_step_or_is_substituted_when_lenient(
    tmp_path,
):
    """&&GHOST with OLD and no earlier NEW: TEMP_NOT_CREATED, or an empty temp."""
    j = job(
        "J",
        (program("S1", "IEFBR14", (_old_delete_dd("GHOST"),)),),
    )
    strict = _runner(tmp_path / "strict", StrictAllocation())
    lenient = _runner(tmp_path / "lenient", LenientAllocation())
    assert (
        strict.run(j, scratch=scratch(tmp_path / "strict")).steps[0].outcome,
        lenient.run(j, scratch=scratch(tmp_path / "lenient")).steps[0].outcome,
    ) == (
        AllocationFailed(DdName("WRK"), AllocationError.TEMP_NOT_CREATED),
        Completed(0),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cleanup_runs_after_step_exception(tmp_path):
    """Temp allocated in step 1 is cleaned up even when step 2 is refused."""
    import pytest

    j = job(
        "J",
        (
            program("S1", "IEFBR14", (_pass_dd("KEPT"),)),
            IfBlock(
                StepName("C1"),
                RcTest(ref("S1"), CondOp.EQ, 0),
                (program("S2", "IEFBR14"),),
            ),
        ),
    )
    with pytest.raises(UnsupportedStep):
        _runner(tmp_path).run(j, scratch=scratch(tmp_path))
    assert _scratch_files(tmp_path) == []


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_job_end_cleanup_removes_undeleted_temp(tmp_path):
    """&&TEMP PASSed by step 1 but never explicitly deleted is cleaned at job end."""
    j = job(
        "J",
        (program("S1", "IEFBR14", (_pass_dd("TEMP"),)),),
    )
    result = _runner(tmp_path).run(j, scratch=scratch(tmp_path))
    assert result.steps[0].outcome == Completed(0)
    assert _scratch_files(tmp_path) == []
