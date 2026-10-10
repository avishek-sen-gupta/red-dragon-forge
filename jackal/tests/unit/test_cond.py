from tests.covers import NotLanguageFeature, covers
from tests.model_build import ran
from jackal.cond import Run, gate
from jackal.model import (
    StepReference,
    AbendMode,
    AllPriorSteps,
    BypassTest,
    CondOp,
    QualifiedStep,
    RcComparison,
    StepCondition,
)
from jackal.results import (
    AfterJobCond,
    BypassReason,
    Bypassed,
    Completed,
    Flushed,
    StepResult,
)

A, B = ran("A"), ran("B")


def _r(step: QualifiedStep, rc: int) -> StepResult:
    return StepResult(step, Completed(rc))


RUN, BYPASS = Run(), Bypassed(BypassReason.COND_SATISFIED)


def _cond(
    *tests: tuple[int, CondOp, StepReference | AllPriorSteps],
    mode: AbendMode = AbendMode.NORMAL,
) -> StepCondition[StepReference]:
    return StepCondition(
        tuple(BypassTest(RcComparison(code, op), t) for code, op, t in tests), mode
    )


def _bypass(
    condition: StepCondition[StepReference], *history: StepResult
) -> Run | Bypassed | Flushed:
    return gate(condition, (), history)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_no_conditions_never_bypasses():
    assert _bypass(_cond(), _r(A, 8)) == RUN


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_test_with_no_step_checks_every_prior_step():
    ne = _cond((0, CondOp.NE, AllPriorSteps()))
    lt = _cond((4, CondOp.LT, AllPriorSteps()))
    assert [
        _bypass(ne, _r(A, 0)),
        _bypass(ne, _r(A, 0), _r(B, 8)),
        _bypass(lt, _r(A, 4)),
        _bypass(lt, _r(A, 8)),
    ] == [RUN, BYPASS, RUN, BYPASS]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_named_step_tests_only_that_step_and_a_step_that_did_not_run_is_false():
    on_a = _cond((0, CondOp.NE, A.reference()))
    on_z = _cond((0, CondOp.NE, ran("ZZZ").reference()))
    bypassed_a = StepResult(A, BYPASS)
    assert [
        _bypass(on_a, _r(A, 0), _r(B, 8)),
        _bypass(on_a, _r(A, 8), _r(B, 0)),
        _bypass(on_z, _r(A, 8)),
        _bypass(on_a, bypassed_a),
    ] == [RUN, BYPASS, RUN, RUN]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_any_true_test_bypasses():
    both = _cond((4, CondOp.LT, AllPriorSteps()), (8, CondOp.EQ, AllPriorSteps()))
    assert [_bypass(both, _r(A, 8)), _bypass(both, _r(A, 0))] == [BYPASS, RUN]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_all_six_operators_compare_code_to_rc():
    history = (_r(A, 5),)

    def holds(code: int, op: CondOp) -> bool:
        return _bypass(_cond((code, op, AllPriorSteps())), *history) == BYPASS

    assert [
        holds(6, CondOp.GT),
        holds(6, CondOp.GE),
        holds(5, CondOp.EQ),
        holds(4, CondOp.NE),
        holds(4, CondOp.LT),
        holds(5, CondOp.LE),
        holds(4, CondOp.GT),
    ] == [True, True, True, True, True, True, False]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_even_reads_as_normal_and_only_always_bypasses_since_nothing_abends():
    lt = (4, CondOp.LT, AllPriorSteps())
    assert [
        _bypass(_cond(lt, mode=AbendMode.EVEN), _r(A, 0)),
        _bypass(_cond(lt, mode=AbendMode.EVEN), _r(A, 8)),
        _bypass(_cond(mode=AbendMode.ONLY), _r(A, 0)),
    ] == [RUN, BYPASS, Bypassed(BypassReason.ONLY_WITHOUT_ABEND)]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_met_job_cond_flushes_naming_the_first_step_that_met_it():
    job_tests = (RcComparison(8, CondOp.LE),)
    on_b = _cond((0, CondOp.NE, B.reference()))
    assert [
        gate(_cond(), job_tests, (_r(A, 4),)),
        gate(_cond(), job_tests, (_r(A, 12), _r(B, 16))),
        gate(on_b, job_tests, (_r(A, 4), _r(B, 12))),
    ] == [RUN, Flushed(AfterJobCond(A)), Flushed(AfterJobCond(B))]
