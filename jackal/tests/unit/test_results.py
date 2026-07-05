from tests.covers import NotLanguageFeature, covers
from jackal.results import StepResult, StepDisposition, JobResult


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_stepresult_defaults_to_executed():
    r = StepResult(name="A", return_code=0, ran=True)
    assert r.disposition is StepDisposition.EXECUTED


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_stepresult_bypassed_is_explicit():
    r = StepResult(
        name="B", return_code=0, ran=False, disposition=StepDisposition.BYPASSED
    )
    assert r.disposition is StepDisposition.BYPASSED and r.ran is False
    JobResult(steps=(r,))  # still composes
