"""Tests for the grammar-based JCL parser."""

from tests.covers import NotLanguageFeature, covers
from jackal.jcl.parser import parse_jcl
from jackal.model import DispNormal, DispStatus

JCL = """//PIPE JOB 'demo'
//STEP1 EXEC PGM=UPCASE
//INDD DD DSN=J.IN,DISP=SHR
//WORKDD DD DSN=J.WORK,DISP=(NEW,PASS,DELETE)
//STEP2 EXEC PGM=STARRER
//WORKDD DD DSN=J.WORK,DISP=SHR
//OUTDD DD DSN=J.OUT,DISP=(NEW,CATLG,DELETE)
"""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_job_steps_and_dds():
    job = parse_jcl(JCL)
    assert job.name == "PIPE"
    assert [s.name for s in job.steps] == ["STEP1", "STEP2"]
    assert [s.pgm for s in job.steps] == ["UPCASE", "STARRER"]
    s1 = job.steps[0]
    assert [d.ddname for d in s1.dds] == ["INDD", "WORKDD"]
    assert s1.dds[1].disp.status is DispStatus.NEW
    assert s1.dds[1].disp.normal is DispNormal.PASS
    assert s1.dds[1].disp.abnormal is DispNormal.DELETE


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_disp_shr_shorthand_defaults_keep():
    job = parse_jcl(JCL)
    indd = job.steps[0].dds[0]
    assert indd.disp.status is DispStatus.SHR
    assert indd.disp.normal is DispNormal.KEEP
    assert indd.disp.abnormal is DispNormal.KEEP


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dd_continuation_line():
    jcl = "//J JOB 1\n//S EXEC PGM=P\n//D DD DSN=A.B,\n//   DISP=(NEW,CATLG,DELETE)\n"
    dd = parse_jcl(jcl).steps[0].dds[0]
    assert dd.dsn == "A.B" and dd.disp.status is DispStatus.NEW
