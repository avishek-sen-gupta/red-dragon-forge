from tests.covers import NotLanguageFeature, covers
from jackal.cond import should_bypass
from jackal.model import Cond, CondOp
from jackal.results import StepResult


def _r(name: str, rc: int) -> StepResult:
    return StepResult(name=name, return_code=rc, ran=True)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_no_conditions_never_bypasses():
    assert should_bypass((), (_r("A", 8),)) is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_0_ne_bypasses_when_any_prior_failed():
    # COND=(0,NE): bypass if 0 NE rc, i.e. any prior rc != 0
    cond = (Cond(code=0, op=CondOp.NE),)
    assert should_bypass(cond, (_r("A", 0),)) is False
    assert should_bypass(cond, (_r("A", 0), _r("B", 8))) is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_4_lt_bypasses_when_prior_rc_above_4():
    # COND=(4,LT): bypass if 4 LT rc, i.e. rc > 4
    cond = (Cond(code=4, op=CondOp.LT),)
    assert should_bypass(cond, (_r("A", 4),)) is False
    assert should_bypass(cond, (_r("A", 8),)) is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_named_step_only_tests_that_step():
    cond = (Cond(code=0, op=CondOp.NE, step="A"),)
    assert should_bypass(cond, (_r("A", 0), _r("B", 8))) is False  # A is 0
    assert should_bypass(cond, (_r("A", 8), _r("B", 0))) is True  # A is 8


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_named_step_not_run_is_false():
    cond = (Cond(code=0, op=CondOp.NE, step="ZZZ"),)
    assert should_bypass(cond, (_r("A", 8),)) is False  # ZZZ never ran


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_multiple_conditions_bypass_if_any():
    cond = (Cond(code=4, op=CondOp.LT), Cond(code=8, op=CondOp.EQ))
    assert should_bypass(cond, (_r("A", 8),)) is True  # 8 EQ 8
    assert should_bypass(cond, (_r("A", 0),)) is False  # neither


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_all_six_operators():
    rc = (_r("A", 5),)
    assert should_bypass((Cond(6, CondOp.GT),), rc) is True  # 6 > 5
    assert should_bypass((Cond(6, CondOp.GE),), rc) is True
    assert should_bypass((Cond(5, CondOp.EQ),), rc) is True
    assert should_bypass((Cond(4, CondOp.NE),), rc) is True
    assert should_bypass((Cond(4, CondOp.LT),), rc) is True  # 4 < 5
    assert should_bypass((Cond(5, CondOp.LE),), rc) is True
    assert should_bypass((Cond(4, CondOp.GT),), rc) is False  # 4 > 5 false
