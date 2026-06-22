from tests.covers import NotLanguageFeature, covers
from jackal.jcl.bridge_parser import JclBridgeParser, JclSubprocessRunner


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_simple_job(jcl_bridge_jar):
    jcl = "//PIPE JOB 1\n//STEP1 EXEC PGM=UPCASE\n//INDD DD DSN=J.IN,DISP=SHR\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.name == "PIPE"
    assert job.steps[0].pgm == "UPCASE"
    assert job.steps[0].dds[0].dsn == "J.IN"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_proc_step(jcl_bridge_jar):
    jcl = "//J JOB 1\n//STEP1 EXEC PROC=MYPROC\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0].pgm == "MYPROC"
