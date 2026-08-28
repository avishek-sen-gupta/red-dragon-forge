"""Parity tests for the bridge-backed JCL parser."""

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.dsn import DirectDSN
from jackal.jcl.parser import parse_jcl
from jackal.model import DispNormal, DispStatus
from jackal.value_parts import literal


@pytest.fixture(autouse=True)
def _require_jcl_bridge(jcl_bridge_jar):
    """parse_jcl now shells to the bridge; ensure JCL_BRIDGE_JAR is set."""


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
    assert dd.dsn == DirectDSN(literal("A.B")) and dd.disp.status is DispStatus.NEW


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dd_star_instream_captured():
    jcl = (
        "//J JOB 1\n//S EXEC PGM=IDCAMS\n//SYSIN DD *\n"
        "   DELETE A.B CLUSTER\n   DEFINE CLUSTER (NAME(A.B))\n/*\n"
    )
    dd = parse_jcl(jcl).steps[0].dds[0]
    assert dd.ddname == "SYSIN"
    assert dd.in_stream == ("   DELETE A.B CLUSTER", "   DEFINE CLUSTER (NAME(A.B))")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dd_star_instream_data_containing_slash_slash_mid_line():
    # Regression: a "//" (or "/*") appearing anywhere in in-stream data, not
    # just at the start of a physical line, must not be mistaken for a JCL
    # statement/comment delimiter — CardDemo's TRANREPT.jcl has a SYMNAMES DD
    # whose data lines end in a stray "//Date" annotation, which used to
    # desync the lexer and silently drop every step after it (including the
    # one that runs CBTRN03C) with no error at all.
    jcl = (
        "//J JOB 1\n//S EXEC PGM=IDCAMS\n//SYSIN DD *\n"
        "HELLO //WORLD\nMORE DATA /* not a real terminator\n/*\n"
        "//S2 EXEC PGM=BAR\n"
    )
    job = parse_jcl(jcl)
    assert [s.name for s in job.steps] == ["S", "S2"]
    dd = job.steps[0].dds[0]
    assert dd.in_stream == ("HELLO //WORLD", "MORE DATA /* not a real terminator")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dd_sysout():
    jcl = "//J JOB 1\n//S EXEC PGM=IDCAMS\n//SYSPRINT DD SYSOUT=*\n"
    dd = parse_jcl(jcl).steps[0].dds[0]
    assert dd.sysout is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dsn_disp_still_parses():  # regression: v1 forms unaffected
    jcl = "//J JOB 1\n//S EXEC PGM=P\n//D DD DSN=A.B,DISP=SHR\n"
    assert parse_jcl(jcl).steps[0].dds[0].dsn == DirectDSN(literal("A.B"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_disp_omitted_trailing_positional():
    """DISP=(NEW,CATLG,) — the grammar keeps the empty slot, so the abnormal
    disposition has to fall back rather than be read as the empty string."""
    jcl = "//J JOB 1\n//S EXEC PGM=P\n//D DD DSN=A.B,DISP=(NEW,CATLG,)\n"
    disp = parse_jcl(jcl).steps[0].dds[0].disp
    assert disp.status is DispStatus.NEW
    assert disp.normal is DispNormal.CATLG
    assert disp.abnormal is DispNormal.CATLG


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_disp_omitted_status_defaults_new():
    """DISP=(,CATLG) — an omitted status is NEW, not the first listed value."""
    jcl = "//J JOB 1\n//S EXEC PGM=P\n//D DD DSN=A.B,DISP=(,CATLG)\n"
    disp = parse_jcl(jcl).steps[0].dds[0].disp
    assert disp.status is DispStatus.NEW
    assert disp.normal is DispNormal.CATLG


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dd_without_disp_defaults_new_delete_delete():
    """No DISP= at all takes the same positional defaults: the data set is
    created by this step, so it is deleted at the end of it."""
    jcl = "//J JOB 1\n//S EXEC PGM=P\n//D DD DSN=A.B\n"
    disp = parse_jcl(jcl).steps[0].dds[0].disp
    assert disp.status is DispStatus.NEW
    assert disp.normal is DispNormal.DELETE
    assert disp.abnormal is DispNormal.DELETE
