from jackal.model import DdName
from jackal.results import (
    Abended,
    AfterAbend,
    AfterAllocationFailure,
    AfterJobCond,
    AllocationError,
    AllocationFailed,
    Bypassed,
    BypassReason,
    Completed,
    Flushed,
    JobAbended,
    JobAllocationFailed,
    JobCompleted,
    JobResult,
    SkippedUnresolved,
    StepResult,
    SystemAbend,
)
from tests.covers import NotLanguageFeature, covers
from tests.model_build import ran


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_job_completes_with_the_highest_rc_among_steps_that_completed():
    a = ran("A")
    result = JobResult(
        (
            StepResult(a, Completed(4)),
            StepResult(ran("B"), Bypassed(BypassReason.COND_SATISFIED)),
            StepResult(ran("C"), Completed(8)),
            StepResult(ran("D"), SkippedUnresolved()),
            StepResult(ran("E"), Flushed(AfterJobCond(a))),
        )
    )
    assert ([s.name for s in result.steps], result.outcome, JobResult(()).outcome) == (
        ["A", "B", "C", "D", "E"],
        JobCompleted(8),
        JobCompleted(0),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_the_first_step_that_could_not_allocate_decides_the_job_outcome():
    first = AllocationFailed(DdName("IN"), AllocationError.DATASET_NOT_FOUND)
    second = AllocationFailed(DdName("TMP"), AllocationError.TEMP_NOT_CREATED)
    b = ran("B")
    result = JobResult(
        (
            StepResult(ran("A"), Completed(0)),
            StepResult(b, first),
            StepResult(ran("C"), second),
        )
    )
    assert (
        result.outcome,
        first.rendered(),
        Flushed(AfterAllocationFailure(b)).rendered(),
        result.outcome.succeeded(),
        JobCompleted(0).succeeded(),
        JobCompleted(4).succeeded(),
    ) == (
        JobAllocationFailed(b, first),
        "allocation failed (DD IN: DATASET_NOT_FOUND)",
        "flushed (allocation failed at B)",
        False,
        True,
        False,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_the_first_abend_or_failed_allocation_decides_the_job_outcome():
    s806 = SystemAbend(0x806)
    missing = AllocationFailed(DdName("IN"), AllocationError.DATASET_NOT_FOUND)
    a, b = ran("A"), ran("B")
    abend_first = JobResult(
        (
            StepResult(a, Abended(s806)),
            StepResult(b, missing),
            StepResult(ran("C"), Flushed(AfterAbend(a))),
        )
    )
    allocation_first = JobResult((StepResult(b, missing), StepResult(a, Abended(s806))))
    assert (
        abend_first.outcome,
        allocation_first.outcome,
        abend_first.outcome.succeeded(),
        Abended(s806).rendered(),
        Flushed(AfterAbend(a)).rendered(),
    ) == (
        JobAbended(a, s806),
        JobAllocationFailed(b, missing),
        False,
        "abended S806",
        "flushed (abended at A)",
    )
