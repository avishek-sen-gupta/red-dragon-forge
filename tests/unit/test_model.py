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
