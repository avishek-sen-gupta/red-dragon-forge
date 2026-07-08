from tests.covers import NotLanguageFeature, covers
from jackal.dsn import DirectDSN, TempRef
from jackal.jcl.bridge_parser import JclBridgeParser, JclSubprocessRunner
from jackal.value_parts import Literal, Symbol, literal


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_simple_job(jcl_bridge_jar):
    jcl = "//PIPE JOB 1\n//STEP1 EXEC PGM=UPCASE\n//INDD DD DSN=J.IN,DISP=SHR\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.name == "PIPE"
    assert job.steps[0].pgm == "UPCASE"
    assert job.steps[0].dds[0].dsn == DirectDSN(literal("J.IN"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_proc_step(jcl_bridge_jar):
    jcl = "//J JOB 1\n//STEP1 EXEC PROC=MYPROC\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0].pgm == "MYPROC"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_parm(jcl_bridge_jar):
    jcl = "//J JOB 1\n//STEP1 EXEC PGM=CBACT04C,PARM='2022071800'\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0].parm == literal("2022071800")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_absent_parm_is_empty_value(jcl_bridge_jar):
    jcl = "//J JOB 1\n//STEP1 EXEC PGM=MYPGM\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0].parm == ()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_symbolic_dsn(jcl_bridge_jar):
    jcl = "//J JOB 1\n//STEP1 EXEC PGM=IDCAMS\n//D DD DISP=SHR,\n//   DSN=&CNTLLIB(REPROCT)\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0].dds[0].dsn == DirectDSN(
        (Symbol("CNTLLIB"), Literal("(REPROCT)"))
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_temp_dsn_as_literal_not_symbol(jcl_bridge_jar):
    # &&TEMP is a doubled-ampersand temp-dataset marker, not a &SYMBOL
    # reference — KEYWORD_VALUE's dedicated temp-file-name alternative must
    # win the lexer tie over SYMBOLIC, or this would misclassify as a Symbol.
    jcl = "//J JOB 1\n//STEP1 EXEC PGM=IEFBR14\n//W DD DSN=&&TEMP,DISP=(NEW,PASS)\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0].dds[0].dsn == TempRef("&&TEMP")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_backward_ref(jcl_bridge_jar):
    jcl = (
        "//J JOB 1\n"
        "//STEP1 EXEC PGM=IEFBR14\n"
        "//WRK DD DSN=MY.FILE,DISP=(NEW,PASS)\n"
        "//STEP2 EXEC PGM=IEFBR14\n"
        "//INPUT DD DSN=*.STEP1.WRK,DISP=(OLD,DELETE)\n"
    )
    from jackal.dsn import BackwardRef

    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    dd = job.steps[1].dds[0]
    assert isinstance(dd.dsn, BackwardRef)
    assert dd.dsn.step == "STEP1"
    assert dd.dsn.ddname == "WRK"
