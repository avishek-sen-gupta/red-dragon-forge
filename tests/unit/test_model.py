from tests.covers import covers, NotLanguageFeature
from jackal.model import DD, Disp, DispNormal, DispStatus, Job, Step


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_job_model_construction():
    dd = DD(
        ddname="INDD",
        dsn="J.IN",
        disp=Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP),
    )
    step = Step(name="STEP1", pgm="UPCASE", dds=(dd,))
    job = Job(name="PIPE", steps=(step,))
    assert job.steps[0].dds[0].ddname == "INDD"
    assert job.steps[0].dds[0].disp.status is DispStatus.SHR


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dd_instream_and_sysout_and_org():
    from jackal.model import DatasetOrg

    dd = DD(
        ddname="SYSIN",
        dsn="",
        disp=Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP),
        in_stream=("  DELETE X CLUSTER",),
        sysout=False,
    )
    assert dd.in_stream == ("  DELETE X CLUSTER",)
    assert DatasetOrg.KSDS.value == "KSDS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cond_model_and_defaults():
    from jackal.model import CondOp, Cond

    c = Cond(code=0, op=CondOp.NE)
    assert c.step == "" and c.op is CondOp.NE and c.code == 0
    step = Step(name="S", pgm="P", dds=(), conds=(c,))
    assert step.conds == (c,)
    job = Job(name="J", steps=(step,), cond=(Cond(code=4, op=CondOp.LT, step="S1"),))
    assert job.cond[0].step == "S1"
    # Step.conds and Job.cond default to empty
    assert Step(name="X", pgm="P", dds=()).conds == ()
    assert Job(name="J2", steps=()).cond == ()
