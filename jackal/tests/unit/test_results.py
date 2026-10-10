from tests.covers import NotLanguageFeature, covers
from tests.model_build import ran
from jackal.results import (
    AfterJobCond,
    BypassReason,
    Bypassed,
    Completed,
    Flushed,
    JobCompleted,
    JobResult,
    SkippedUnresolved,
    StepResult,
)


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
