package org.jackal.jcl;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.Test;

import static org.junit.Assert.assertEquals;

/** The JSON contract: what each JCL construct becomes, compared whole. */
public class ContractTest {

    private static final String JOB_CARD = "//ACCEPT JOB (A),CLASS=A";

    private static JsonObject serialize(String... lines) {
        return JclSerializer.serialize(String.join("\n", lines) + "\n");
    }

    private static JsonElement json(String text) {
        return JsonParser.parseString(text.replace('\'', '"'));
    }

    private static JsonElement statements(String... lines) {
        String[] withCard = new String[lines.length + 1];
        withCard[0] = JOB_CARD;
        System.arraycopy(lines, 0, withCard, 1, lines.length);
        return serialize(withCard).get("statements");
    }

    private static JsonElement onlyDds(String... ddLines) {
        String[] lines = new String[ddLines.length + 1];
        lines[0] = "//S1 EXEC PGM=PGMA";
        System.arraycopy(ddLines, 0, lines, 1, ddLines.length);
        return statements(lines).getAsJsonArray().get(0).getAsJsonObject().get("dds");
    }

    private static final String NO_COND = "{'tests':[],'mode':'NORMAL'}";

    private static String literal(String text) {
        return "{'kind':'literal','text':'" + text + "'}";
    }

    private static final String UNCODED_ATTRIBUTES =
            ",'dcb':{'coded':false,'source':{'kind':'none'},'recfm':[],'lrecl':[]},'gdg_order':[]";

    private static String named(String ddname, String dsn, String disp) {
        return "{'ddname':'" + ddname + "','dsn':{'kind':'name','value':[" + literal(dsn)
                + "]},'disp':" + disp + ",'nullified':[],'in_stream':[],'sysout':false,'concatenated':[]" + UNCODED_ATTRIBUTES + "}";
    }

    @Test
    public void aJobCarriesItsNameItsEndJobTestsAndItsStatements() {
        assertEquals(
                json("{'kind':'job','name':'ACCEPT',"
                        + "'end_job_tests':[{'code':8,'op':'LE'},{'code':12,'op':'EQ'}],"
                        + "'statements':[{'kind':'program','label':'S1','pgm':'PGMA','parm':[],"
                        + "'cond':" + NO_COND + ",'dds':[]}]}"),
                serialize("//ACCEPT JOB (A),CLASS=A,COND=((8,LE),(12,EQ))", "//S1 EXEC PGM=PGMA"));
    }

    @Test
    public void aProgramStepCarriesItsLabelParmAndCondition() {
        assertEquals(
                json("[{'kind':'program','label':'S1','pgm':'PGMA','parm':[" + literal("A=(,255)")
                        + "],'cond':" + NO_COND + ",'dds':[]},"
                        + "{'kind':'program','label':'','pgm':'PGMB','parm':[" + literal("X (Y")
                        + "],'cond':" + NO_COND + ",'dds':[]}]"),
                statements("//S1 EXEC PGM=PGMA,PARM='A=(,255)'", "// EXEC PGM=PGMB,PARM='X (Y'"));
    }

    @Test
    public void aConditionSplitsItsTestsFromItsModeWhereverTheModeSits() {
        String allPrior = "{'kind':'all_prior'}";
        String s1 = "{'kind':'step','step':'S1'}";
        String s1p1 = "{'kind':'proc_step','call':'S1','step':'P1'}";
        assertEquals(
                json("[{'tests':[{'code':4,'op':'LT','target':" + allPrior + "}],'mode':'NORMAL'},"
                        + "{'tests':[{'code':4,'op':'LT','target':" + allPrior + "},"
                        + "{'code':8,'op':'EQ','target':" + s1 + "}],'mode':'NORMAL'},"
                        + "{'tests':[{'code':4,'op':'LT','target':" + s1p1 + "}],'mode':'NORMAL'},"
                        + "{'tests':[],'mode':'EVEN'},"
                        + "{'tests':[],'mode':'ONLY'},"
                        + "{'tests':[{'code':4,'op':'LT','target':" + allPrior + "},"
                        + "{'code':8,'op':'EQ','target':" + s1 + "}],'mode':'EVEN'},"
                        + "{'tests':[{'code':4,'op':'LT','target':" + allPrior + "}],'mode':'ONLY'},"
                        + "{'tests':[],'mode':'EVEN'}]"),
                conds(
                        "COND=(4,LT)",
                        "COND=((4,LT),(8,EQ,S1))",
                        "COND=(4,LT,S1.P1)",
                        "COND=EVEN",
                        "COND=ONLY",
                        "COND=((4,LT),EVEN,(8,EQ,S1))",
                        "COND=(ONLY,(4,LT))",
                        "COND=(EVEN)"));
    }

    private static JsonElement conds(String... parameters) {
        String[] lines = new String[parameters.length];
        for (int i = 0; i < parameters.length; i++) {
            lines[i] = "//S" + i + " EXEC PGM=PGMA," + parameters[i];
        }
        com.google.gson.JsonArray result = new com.google.gson.JsonArray();
        statements(lines).getAsJsonArray()
                .forEach(s -> result.add(s.getAsJsonObject().get("cond")));
        return result;
    }

    @Test
    public void aProcCallSplitsEachOverrideFromItsQualifier() {
        String nullify = "{'tests':[],'mode':'NORMAL'}";
        assertEquals(
                json("[{'kind':'proc_call','label':'S1','proc':'TWO',"
                        + "'symbol_overrides':[{'name':'HLQ','value':[" + literal("PROD") + "]}],"
                        + "'parm_overrides':[{'procstep':'','parm':[" + literal("X") + "]},"
                        + "{'procstep':'P2','parm':[" + literal("Y") + "]},"
                        + "{'procstep':'P1','parm':[]}],"
                        + "'cond_overrides':[{'procstep':'','cond':{'tests':[{'code':4,'op':'LT',"
                        + "'target':{'kind':'all_prior'}}],'mode':'NORMAL'}},"
                        + "{'procstep':'P2','cond':" + nullify + "}],"
                        + "'dd_overrides':["
                        + "{'procstep':'','dd':" + named("IN", "T.NEWIN", "['SHR']") + "},"
                        + "{'procstep':'P2','dd':" + named("OUT", "T.NEWOUT", "['SHR']") + "},"
                        + "{'procstep':'','dd':" + named("EXTRA", "T.EXTRA", "['SHR']") + "}]}]"),
                statements(
                        "//S1 EXEC TWO,HLQ=PROD,PARM='X',PARM.P2='Y',PARM.P1='',",
                        "//  COND=(4,LT),COND.P2=",
                        "//IN DD DSN=T.NEWIN,DISP=SHR",
                        "//P2.OUT DD DSN=T.NEWOUT,DISP=SHR",
                        "//EXTRA DD DSN=T.EXTRA,DISP=SHR"));
    }

    @Test
    public void procIsTheSameCallAsANamedProc() {
        assertEquals(
                json("[{'kind':'proc_call','label':'S3','proc':'MYP','symbol_overrides':[],"
                        + "'parm_overrides':[],'cond_overrides':[],'dd_overrides':[]}]"),
                statements("//S3 EXEC PROC=MYP"));
    }

    @Test
    public void eachDsnKindIsTaggedAndAPeriodAfterASymbolIsDropped() {
        String none = ",'disp':[],'nullified':[],'in_stream':[],'sysout':false,'concatenated':[]" + UNCODED_ATTRIBUTES + "}";
        assertEquals(
                json("[{'ddname':'A','dsn':{'kind':'name','value':[{'kind':'symbol','name':'HLQ'},"
                        + literal(".X") + "]}" + none + ","
                        + "{'ddname':'B','dsn':{'kind':'name','value':[{'kind':'symbol','name':'T'}]}" + none + ","
                        + "{'ddname':'C','dsn':{'kind':'temp','name':'WORK'}" + none + ","
                        + "{'ddname':'D','dsn':{'kind':'backref','target':{'kind':'step','step':'S0'},"
                        + "'ddname':'IN'}" + none + ","
                        + "{'ddname':'E','dsn':{'kind':'backref','target':{'kind':'proc_step',"
                        + "'call':'S0','step':'P1'},'ddname':'IN'}" + none + ","
                        + "{'ddname':'F','dsn':{'kind':'dummy'}" + none + ","
                        + "{'ddname':'G','dsn':{'kind':'dummy'}" + none + ","
                        + "{'ddname':'H','dsn':{'kind':'none'},'disp':[],'nullified':[],'in_stream':[],'sysout':true,"
                        + "'concatenated':[]" + UNCODED_ATTRIBUTES + "}]"),
                onlyDds(
                        "//A DD DSN=&HLQ..X",
                        "//B DD DSN=&T",
                        "//C DD DSN=&&WORK",
                        "//D DD DSN=*.S0.IN",
                        "//E DD DSN=*.S0.P1.IN",
                        "//F DD DUMMY",
                        "//G DD DSN=NULLFILE",
                        "//H DD SYSOUT=*"));
    }

    @Test
    public void inStreamAndDataCardsAreBothKept() {
        String rest = ",'disp':[],'nullified':[],'sysout':false,'concatenated':[]" + UNCODED_ATTRIBUTES + "}";
        assertEquals(
                json("[{'ddname':'SYSIN','dsn':{'kind':'in_stream'},'in_stream':[' CARD ONE',' CARD TWO']"
                        + rest + ","
                        + "{'ddname':'DATA1','dsn':{'kind':'in_stream'},'in_stream':[' DATA LINE']" + rest
                        + "]"),
                onlyDds(
                        "//SYSIN DD *",
                        " CARD ONE",
                        " CARD TWO",
                        "/*",
                        "//DATA1 DD DATA",
                        " DATA LINE",
                        "/*"));
    }

    @Test
    public void unnamedDdsAreMembersOfTheNamedDdBeforeThem() {
        String shr = "['SHR']";
        assertEquals(
                json("[{'ddname':'MIXED','dsn':{'kind':'name','value':[" + literal("T.F") + "]},"
                        + "'disp':" + shr + ",'nullified':[],'in_stream':[],'sysout':false,'concatenated':["
                        + "{'dsn':{'kind':'name','value':[" + literal("T.G") + "]},'disp':" + shr
                        + ",'nullified':[],'in_stream':[]},"
                        + "{'dsn':{'kind':'in_stream'},'disp':[],'nullified':[],'in_stream':[' CARD']},"
                        + "{'dsn':{'kind':'dummy'},'disp':[],'nullified':[],'in_stream':[]}]" + UNCODED_ATTRIBUTES + "},"
                        + named("LAST", "T.H", shr) + "]"),
                onlyDds(
                        "//MIXED DD DSN=T.F,DISP=SHR",
                        "// DD DSN=T.G,DISP=SHR",
                        "// DD *",
                        " CARD",
                        "/*",
                        "// DD DUMMY",
                        "//LAST DD DSN=T.H,DISP=SHR"));
    }

    private static String program(String label, String pgm) {
        return "{'kind':'program','label':'" + label + "','pgm':'" + pgm + "','parm':[],'cond':"
                + NO_COND + ",'dds':[]}";
    }

    @Test
    public void ifBlocksNestTheStatementsBetweenThem() {
        String s1rc = "{'kind':'rc','target':{'kind':'step','step':'S1'},'op':'EQ','code':0}";
        String s2rc = "{'kind':'rc','target':{'kind':'step','step':'S2'},'op':'GT','code':4}";
        assertEquals(
                json("[" + program("S1", "PGMA") + ","
                        + "{'kind':'if','label':'C1','condition':" + s1rc + ",'then':["
                        + program("S2", "PGMB") + ","
                        + "{'kind':'if','label':'C2','condition':" + s2rc + ",'then':["
                        + program("S3", "PGMC") + "],'otherwise':[]}],"
                        + "'otherwise':[" + program("S4", "PGMD") + "]},"
                        + program("S5", "PGME") + "]"),
                statements(
                        "//S1 EXEC PGM=PGMA",
                        "//C1 IF (S1.RC = 0) THEN",
                        "//S2 EXEC PGM=PGMB",
                        "//C2 IF (S2.RC > 4) THEN",
                        "//S3 EXEC PGM=PGMC",
                        "// ENDIF",
                        "// ELSE",
                        "//S4 EXEC PGM=PGMD",
                        "// ENDIF",
                        "//S5 EXEC PGM=PGME"));
    }

    @Test
    public void aSetStatementKeepsItsAssignmentsInOrderWhereverItSits() {
        String set = "{'kind':'set','assignments':[{'name':'HLQ','value':[" + literal("T1") + "]},"
                + "{'name':'LIB','value':[{'kind':'symbol','name':'HLQ'}," + literal(".LIB") + "]},"
                + "{'name':'SFX','value':[]}]}";
        String s1rc = "{'kind':'rc','target':{'kind':'step','step':'S1'},'op':'EQ','code':0}";
        assertEquals(
                json("[" + set + "," + program("S1", "PGMA") + ","
                        + "{'kind':'if','label':'C1','condition':" + s1rc + ",'then':["
                        + program("S2", "PGMB") + "],'otherwise':["
                        + "{'kind':'set','assignments':[{'name':'HLQ','value':[" + literal("T4") + "]}]}]}]"),
                statements(
                        "// SET HLQ=T1,LIB=&HLQ..LIB,SFX=",
                        "//S1 EXEC PGM=PGMA",
                        "//C1 IF (S1.RC = 0) THEN",
                        "//S2 EXEC PGM=PGMB",
                        "// ELSE",
                        "// SET HLQ=T4",
                        "// ENDIF"));
        assertEquals(
                json("[{'kind':'set','assignments':[{'name':'MODE','value':[" + literal("P") + "]}]},"
                        + program("P1", "PGMA") + "]"),
                serialize("//SETP PROC LIB=X", "// SET MODE=P", "//P1 EXEC PGM=PGMA")
                        .get("statements"));
    }

    private static JsonElement condition(String expression) {
        return statements("//T IF " + expression + " THEN", "//S EXEC PGM=PGMA", "// ENDIF")
                .getAsJsonArray().get(0).getAsJsonObject().get("condition");
    }

    @Test
    public void eachIfTermBecomesItsExpression() {
        String all = "{'kind':'all_prior'}";
        String s1 = "{'kind':'step','step':'S1'}";
        String s1p1 = "{'kind':'proc_step','call':'S1','step':'P1'}";
        assertEquals(
                json("[{'kind':'rc','target':" + all + ",'op':'LE','code':4},"
                        + "{'kind':'rc','target':" + s1 + ",'op':'GE','code':2},"
                        + "{'kind':'abend','target':" + all + "},"
                        + "{'kind':'abend','target':" + s1p1 + "},"
                        + "{'kind':'not','operand':{'kind':'abend','target':" + all + "}},"
                        + "{'kind':'not','operand':{'kind':'abend','target':" + all + "}},"
                        + "{'kind':'not','operand':{'kind':'run','target':" + s1 + "}},"
                        + "{'kind':'abend_code','target':" + all + ",'abend':{'kind':'user','code':100}},"
                        + "{'kind':'abend_code','target':" + s1 + ",'abend':{'kind':'system','code':199}},"
                        + "{'kind':'run','target':" + s1 + "}]"),
                array(
                        condition("RC NG 4"),
                        condition("S1.RC NL 2"),
                        condition("ABEND"),
                        condition("S1.P1.ABEND = TRUE"),
                        condition("¬ABEND"),
                        condition("ABEND = FALSE"),
                        condition("NOT S1.RUN"),
                        condition("ABENDCC = U0100"),
                        condition("S1.ABENDCC = S0C7"),
                        condition("S1.RUN")));
    }

    @Test
    public void andAndOrHaveEqualPrecedenceReadLeftToRight() {
        String run = "{'kind':'run','target':{'kind':'step','step':'S1'}}";
        String rc = "{'kind':'rc','target':{'kind':'step','step':'S1'},'op':'LT','code':8}";
        String notAbend = "{'kind':'not','operand':{'kind':'abend','target':{'kind':'step','step':'S1'}}}";
        assertEquals(
                json("[{'kind':'and','operands':[" + run + ",{'kind':'or','operands':[" + rc + ","
                        + notAbend + "]}]},"
                        + "{'kind':'and','operands':[{'kind':'or','operands':[" + run + "," + rc + "]},"
                        + notAbend + "]},"
                        + "{'kind':'or','operands':[" + run + "," + rc + "," + notAbend + "]}]"),
                array(
                        condition("S1.RUN AND (S1.RC < 8 OR NOT S1.ABEND)"),
                        condition("S1.RUN | S1.RC < 8 & ¬S1.ABEND"),
                        condition("S1.RUN OR S1.RC LT 8 OR NOT S1.ABEND")));
    }

    private static JsonElement array(JsonElement... elements) {
        com.google.gson.JsonArray result = new com.google.gson.JsonArray();
        for (JsonElement e : elements) {
            result.add(e);
        }
        return result;
    }

    @Test
    public void aProcDefaultMayHoldASymbolOrATemporaryName() {
        assertEquals(
                json("[{'name':'HLQ','value':[" + literal("TEST") + "]},"
                        + "{'name':'DS','value':[{'kind':'symbol','name':'HLQ'}," + literal(".DATA") + "]},"
                        + "{'name':'T','value':[" + literal("&&TMP") + "]},"
                        + "{'name':'B','value':[{'kind':'symbol','name':'A'}]}]"),
                serialize("//P PROC HLQ=TEST,DS=&HLQ..DATA,T=&&TMP,B=&A", "//S1 EXEC PGM=X")
                        .get("defaults"));
    }

    @Test
    public void aProcDocumentCarriesItsDefaultsAndStatements() {
        assertEquals(
                json("{'kind':'proc','name':'SYMP',"
                        + "'defaults':[{'name':'HLQ','value':[" + literal("T") + "]},"
                        + "{'name':'EMPTY','value':[]}],"
                        + "'statements':[{'kind':'program','label':'P1','pgm':'PGMA',"
                        + "'parm':[{'kind':'symbol','name':'SUFFIX'}],'cond':" + NO_COND + ",'dds':[]},"
                        + "{'kind':'if','label':'I1','condition':{'kind':'rc','target':"
                        + "{'kind':'step','step':'P1'},'op':'EQ','code':0},'then':["
                        + "{'kind':'program','label':'P2','pgm':'PGMB','parm':[],'cond':" + NO_COND
                        + ",'dds':[]}],'otherwise':[]}]}"),
                serialize(
                        "//SYMP PROC HLQ=T,EMPTY=",
                        "//P1 EXEC PGM=PGMA,PARM='&SUFFIX'",
                        "//I1 IF (P1.RC = 0) THEN",
                        "//P2 EXEC PGM=PGMB",
                        "// ENDIF"));
    }
}
