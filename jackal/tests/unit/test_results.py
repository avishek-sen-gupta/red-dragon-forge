from tests.covers import NotLanguageFeature, covers
from tests.model_build import ran
from jackal.results import JobResult, StepDisposition, StepResult


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_step_result_renders_its_step_and_says_whether_it_ran():
    executed = StepResult(ran("A"), 0)
    bypassed = StepResult(ran("B"), 0, StepDisposition.BYPASSED)
    assert [
        (r.name, r.ran, r.disposition) for r in JobResult((executed, bypassed)).steps
    ] == [
        ("A", True, StepDisposition.EXECUTED),
        ("B", False, StepDisposition.BYPASSED),
    ]
