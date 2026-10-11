from jackal.expansion import DirectoryProcLibrary
from jackal.jcl.bridge_parser import JclBridgeParser, JclSubprocessRunner
from jackal.model import (
    UnresolvedDd,
    DdName,
    DirectDSN,
    OwnScope,
    ProcCall,
    ProcRef,
    ProgramRef,
    StepName,
    StepRef,
    TempRef,
)
from jackal.value_parts import Literal, Symbol, SymbolName, literal
from tests.covers import NotLanguageFeature, covers

_NO_LIBRARY = DirectoryProcLibrary(())


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_simple_job(jcl_bridge_jar):
    jcl = "//PIPE JOB 1\n//STEP1 EXEC PGM=UPCASE\n//INDD DD DSN=J.IN,DISP=SHR\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.name == "PIPE"
    assert job.steps[0].pgm == ProgramRef("UPCASE")
    assert job.steps[0].dds[0].dsn == DirectDSN(literal("J.IN"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_proc_step(jcl_bridge_jar):
    jcl = "//J JOB 1\n//STEP1 EXEC PROC=MYPROC\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0] == ProcCall(StepName("STEP1"), ProcRef("MYPROC"))


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
        (Symbol(SymbolName("CNTLLIB")), Literal("(REPROCT)"))
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_temp_dsn_as_literal_not_symbol(jcl_bridge_jar):
    # &&TEMP is a doubled-ampersand temp-dataset marker, not a &SYMBOL
    # reference — KEYWORD_VALUE's dedicated temp-file-name alternative must
    # win the lexer tie over SYMBOLIC, or this would misclassify as a Symbol.
    jcl = "//J JOB 1\n//STEP1 EXEC PGM=IEFBR14\n//W DD DSN=&&TEMP,DISP=(NEW,PASS)\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0].dds[0].dsn == TempRef("TEMP")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_backward_ref(jcl_bridge_jar):
    jcl = (
        "//J JOB 1\n"
        "//STEP1 EXEC PGM=IEFBR14\n"
        "//WRK DD DSN=MY.FILE,DISP=(NEW,PASS)\n"
        "//STEP2 EXEC PGM=IEFBR14\n"
        "//INPUT DD DSN=*.STEP1.WRK,DISP=(OLD,DELETE)\n"
    )
    from jackal.model import BackwardRef

    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    dd = job.steps[1].dds[0]
    assert isinstance(dd.dsn, BackwardRef)
    assert dd.dsn == BackwardRef(
        StepRef(OwnScope(), StepName("STEP1")), UnresolvedDd(DdName("WRK"))
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_proc_document(jcl_bridge_jar):
    jcl = (
        "//REPROC PROC\n"
        "//PRC001 EXEC PGM=IDCAMS\n"
        "//FILEIN  DD DISP=SHR,DSN=NULLFILE\n"
        "//SYSIN   DD DISP=SHR,DSN=&CNTLLIB(REPROCT)\n"
        "// PEND\n"
    )
    proc = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse_proc(jcl)
    assert proc.name == "REPROC"
    assert proc.defaults == ()
    assert [s.label for s in proc.steps] == [StepName("PRC001")]
    assert proc.steps[0].dds[1].dsn == DirectDSN(
        (Symbol(SymbolName("CNTLLIB")), Literal("(REPROCT)"))
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_exec_proc_parm_override(jcl_bridge_jar):
    jcl = "//J JOB 1\n//STEP1 EXEC PROC=REPROC,CNTLLIB=AWS.M2.CARDDEMO.CNTL\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0].symbol_overrides == (
        (SymbolName("CNTLLIB"), literal("AWS.M2.CARDDEMO.CNTL")),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_a_relative_generation_as_its_gdg_base_and_number(
    jcl_bridge_jar,
):
    """z/OS 3.1 JCL Reference, DD DSNAME, p. 166: a relative generation number
    starts with +, - or 0 and the rest is numeric; a member name starts with a
    letter or national character."""
    from jackal.expansion import expand_or_fail
    from jackal.model import GenerationDSN

    jcl = (
        "//J JOB 1\n"
        "// SET HLQ=PROD\n"
        "//S1 EXEC PGM=A\n"
        "//NEXT DD DSN=P.HIST(+1),DISP=(NEW,CATLG)\n"
        "//CURR DD DSN=P.HIST(0),DISP=SHR\n"
        "//PREV DD DSN=P.HIST(-002),DISP=SHR\n"
        "//SYMB DD DSN=&HLQ..HIST(+1),DISP=SHR\n"
        "//MEMB DD DSN=P.PDS(MEMBER1),DISP=SHR\n"
        "//ABSL DD DSN=P.HIST.G0001V00,DISP=SHR\n"
    )
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    expanded = expand_or_fail(job, _NO_LIBRARY)
    assert [dd.dsn for dd in expanded.steps[0].step.dds] == [
        GenerationDSN(literal("P.HIST"), 1),
        GenerationDSN(literal("P.HIST"), 0),
        GenerationDSN(literal("P.HIST"), -2),
        GenerationDSN(literal("PROD.HIST"), 1),
        DirectDSN(literal("P.PDS(MEMBER1)")),
        DirectDSN(literal("P.HIST.G0001V00")),
    ]
