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


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_dcb_attributes_and_model_however_coded(jcl_bridge_jar):
    """Record A1 (JCL Ref pp. 127-128): RECFM and LRECL coded inside DCB= or as
    DD keywords are one attribute; a dsname, *.step.dd or *.dd is the model."""
    from jackal.expansion import expand_or_fail
    from jackal.model import BackwardRef, Dcb, NoDSN, StepDd

    jcl = (
        "//J JOB 1\n"
        "// SET LR=204\n"
        "//S0 EXEC PGM=A\n"
        "//OUT DD DSN=T.OUT,DISP=(NEW,CATLG),DCB=(RECFM=FB,LRECL=60)\n"
        "//S1 EXEC PGM=A\n"
        "//A DD DSN=T.A,DISP=(NEW,CATLG),\n"
        "//         DCB=(T.MODEL,RECFM=FB,LRECL=80,BLKSIZE=800)\n"
        "//B DD DSN=T.B,DISP=(NEW,CATLG),RECFM=VB,LRECL=&LR,BLKSIZE=0\n"
        "//C DD DSN=T.C,DISP=(NEW,CATLG),DCB=*.S0.OUT\n"
        "//D DD DSN=T.D,DISP=SHR\n"
        "//E DD DSN=T.E,DISP=(NEW,CATLG),DCB=*.A\n"
    )
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert [dd.dcb for dd in job.steps[-1].dds] == [
        Dcb(DirectDSN(literal("T.MODEL")), literal("FB"), literal("80")),
        Dcb(NoDSN(), literal("VB"), (Symbol(SymbolName("LR")),)),
        Dcb(
            BackwardRef(
                StepRef(OwnScope(), StepName("S0")), UnresolvedDd(DdName("OUT"))
            ),
            (),
            (),
        ),
        Dcb(NoDSN(), (), ()),
        Dcb(StepDd(DdName("A")), (), ()),
    ]
    expanded = expand_or_fail(job, _NO_LIBRARY)
    assert expanded.steps[-1].step.dds[1].dcb == Dcb(
        NoDSN(), literal("VB"), literal("204")
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_overrides_dcb_subparameters_one_by_one(jcl_bridge_jar, tmp_path):
    """Record A8 (JCL Ref p. 75): an override changes only the DCB keywords it
    codes, keeps the model only if it codes DCB= without one dropping it, nullifies
    a keyword coded empty, and DUMMY keeps the DCB. DCB= empty clears it all."""
    from jackal.expansion import expand_or_fail
    from jackal.model import Dcb, NoDSN

    (tmp_path / "P.prc").write_text(
        "//P PROC\n"
        "//PS EXEC PGM=A\n"
        "//D1 DD DSN=T.D1,DISP=(NEW,CATLG),DCB=(T.MOD,RECFM=FB,LRECL=80)\n"
        "//D2 DD DSN=T.D2,DISP=(NEW,CATLG),DCB=(T.MOD,RECFM=FB,LRECL=80)\n"
        "//D3 DD DSN=T.D3,DISP=(NEW,CATLG),DCB=(T.MOD,RECFM=FB,LRECL=80)\n"
        "//D4 DD DSN=T.D4,DISP=(NEW,CATLG),DCB=(T.MOD,RECFM=FB,LRECL=80)\n"
        "//D5 DD DSN=T.D5,DISP=(NEW,CATLG),DCB=(T.MOD,RECFM=FB,LRECL=80)\n"
        "// PEND\n"
    )
    jcl = (
        "//J JOB 1\n"
        "//S EXEC P\n"
        "//PS.D1 DD LRECL=100\n"
        "//PS.D2 DD DCB=(RECFM=VB)\n"
        "//PS.D3 DD RECFM=\n"
        "//PS.D4 DD DUMMY\n"
        "//PS.D5 DD DCB=\n"
    )
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    expanded = expand_or_fail(job, DirectoryProcLibrary((tmp_path,)))
    model = DirectDSN(literal("T.MOD"))
    assert [dd.dcb for dd in expanded.steps[0].step.dds] == [
        Dcb(model, literal("FB"), literal("100")),
        Dcb(NoDSN(), literal("VB"), literal("80")),
        Dcb(model, (), literal("80")),
        Dcb(model, literal("FB"), literal("80")),
        Dcb(NoDSN(), (), ()),
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_a_same_step_referback(jcl_bridge_jar):
    """JCL Ref, DD DSNAME: *.ddname refers to an earlier DD of the same step."""
    from jackal.model import StepDd

    jcl = (
        "//J JOB 1\n"
        "//S1 EXEC PGM=A\n"
        "//IN DD DSN=T.IN,DISP=SHR\n"
        "//AGAIN DD DSN=*.IN,DISP=SHR\n"
    )
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0].dds[1].dsn == StepDd(DdName("IN"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_applies_a_set_inside_a_proc_below_its_exec_and_proc_values(
    jcl_bridge_jar, tmp_path
):
    """JCL Ref p. 48, Table 13: inside a procedure a symbol takes the calling EXEC's
    value, then the PROC statement's default, then a SET's, then the value from
    outside. A SET applies to the statements after it."""
    from jackal.expansion import expand_or_fail

    (tmp_path / "P.prc").write_text(
        "//P PROC C=PDEF\n"
        "//S1 EXEC PGM=A\n"
        "//D DD DSN=&A..&B..&C,DISP=SHR\n"
        "// SET A=SETA,B=SETB,C=SETC\n"
        "//S2 EXEC PGM=A\n"
        "//D DD DSN=&A..&B..&C,DISP=SHR\n"
        "// PEND\n"
    )
    jcl = "//J JOB 1\n// SET B=JOBB\n//J1 EXEC P,A=EXECA\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    expanded = expand_or_fail(job, DirectoryProcLibrary((tmp_path,)))
    assert [s.step.dds[0].dsn for s in expanded.steps] == [
        DirectDSN(literal("EXECA.JOBB.PDEF")),
        DirectDSN(literal("EXECA.SETB.PDEF")),
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_a_null_symbolic_override_on_exec(jcl_bridge_jar):
    """JCL Ref, EXEC statement: symbol= with no value nullifies the symbol for the
    procedure. It used to fail the whole job with 'no viable alternative'."""
    jcl = "//J JOB 1\n//S1 EXEC PROC=P1,A=,C=789\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0].symbol_overrides == (
        (SymbolName("A"), ()),
        (SymbolName("C"), literal("789")),
    )
