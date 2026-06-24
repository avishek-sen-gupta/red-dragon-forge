import pytest
from tests.covers import NotLanguageFeature, covers
from jackal.jcl.parser import parse_jcl
from jackal.model import CondOp


@pytest.fixture(autouse=True)
def _require_jcl_bridge(jcl_bridge_jar):
    """parse_jcl shells to the bridge; ensure JCL_BRIDGE_JAR is set."""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bridge_emits_step_cond():
    job = parse_jcl("//J JOB 1\n//S EXEC PGM=P,COND=(0,NE)\n")
    assert job.steps[0].conds == (
        __import__("jackal.model", fromlist=["Cond"]).Cond(code=0, op=CondOp.NE),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bridge_emits_multiple_conditions():
    job = parse_jcl("//J JOB 1\n//S EXEC PGM=P,COND=((4,LT),(8,EQ))\n")
    ops = [(c.code, c.op) for c in job.steps[0].conds]
    assert ops == [(4, CondOp.LT), (8, CondOp.EQ)]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bridge_emits_cond_with_stepname():
    job = parse_jcl("//J JOB 1\n//A EXEC PGM=P\n//B EXEC PGM=Q,COND=(0,NE,A)\n")
    assert job.steps[1].conds[0].step == "A"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bridge_cond_even_fails_loud():
    from jackal.jcl.bridge_parser import JclParseError

    with pytest.raises(JclParseError):
        parse_jcl("//J JOB 1\n//S EXEC PGM=P,COND=EVEN\n")
