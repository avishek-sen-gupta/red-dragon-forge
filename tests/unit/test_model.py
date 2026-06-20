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
