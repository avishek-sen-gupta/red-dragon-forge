package org.jackal.jcl;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

/**
 * A bare {@code /*} between steps -- or between the DD statements of one step --
 * does not end the job.
 *
 * <p>Bare {@code /*} is the JES2 delimiter statement, not a comment ({@code //*}
 * is the comment). It terminates in-stream data, and z/OS permits it anywhere in
 * a job -- including on its own, terminating nothing.
 *
 * <p>{@code execJCL} used to list {@code delimiterStatement} only in the tail of
 * a statement group, and it spells that group out twice rather than looping it,
 * so a job could hold exactly ONE interior delimiter. The second one closed the
 * job and the enclosing {@code ( ... )+} restarted wanting a fresh JOB card,
 * reported as {@code mismatched input 'EXEC' expecting JOB} at the next step.
 * On the production corpus that cost 188 of 860 members every step they had.
 */
public class DelimiterStatementTest {

    /** Step count for a job built from the given lines. */
    private static int steps(String... lines) {
        JsonObject job = JclSerializer.serialize(String.join("\n", lines) + "\n");
        return job.getAsJsonArray("steps").size();
    }

    /** The DD names of the job's only step, so a swallowed DD shows as an absence. */
    private static JsonArray ddNames(String... lines) {
        JsonObject job = JclSerializer.serialize(String.join("\n", lines) + "\n");
        JsonArray steps = job.getAsJsonArray("steps");
        assertEquals("expected exactly one step", 1, steps.size());
        JsonArray names = new JsonArray();
        for (var dd : steps.get(0).getAsJsonObject().getAsJsonArray("dds")) {
            names.add(dd.getAsJsonObject().get("ddname"));
        }
        return names;
    }

    private static JsonArray namesOf(String... names) {
        JsonArray expected = new JsonArray();
        for (String name : names) {
            expected.add(name);
        }
        return expected;
    }

    @Test
    public void oneInteriorDelimiterIsAbsorbed() {
        assertEquals(
                2,
                steps(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEFBR14",
                        "/*",
                        "//STEP2    EXEC PGM=IEFBR14"));
    }

    @Test
    public void aSecondInteriorDelimiterDoesNotEndTheJob() {
        assertEquals(
                3,
                steps(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEFBR14",
                        "/*",
                        "//STEP2    EXEC PGM=IEFBR14",
                        "/*",
                        "//STEP3    EXEC PGM=IEFBR14"));
    }

    @Test
    public void everyInteriorDelimiterInALongJobIsAbsorbed() {
        assertEquals(
                4,
                steps(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEFBR14",
                        "/*",
                        "//STEP2    EXEC PGM=IEFBR14",
                        "/*",
                        "//STEP3    EXEC PGM=IEFBR14",
                        "/*",
                        "//STEP4    EXEC PGM=IEFBR14",
                        "/*"));
    }

    /**
     * The other {@code /*}: one that really does terminate in-stream data. The
     * lexer consumes it inside {@code DATA_MODE} as {@code
     * DATA_MODE_TERMINATOR3}, so the parser never sees a delimiterStatement
     * token for it -- both kinds have to work in the same job.
     */
    @Test
    public void aDelimiterTerminatingInStreamDataStillCountsForNothing() {
        assertEquals(
                3,
                steps(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEBGENER",
                        "//SYSIN    DD *",
                        "  GENERATE MAXFLDS=1",
                        "/*",
                        "//STEP2    EXEC PGM=IEFBR14",
                        "/*",
                        "//STEP3    EXEC PGM=IEFBR14"));
    }

    /**
     * The commonest shape in the production corpus: a bare {@code /*} sitting
     * between two DD statements of ONE step, terminating nothing.
     *
     * <p>{@code jclStep} listed no delimiterStatement at all, so the step's DD
     * list ended at the delimiter, the job ended with it, and {@code execJCL+}
     * restarted demanding a fresh JOB card -- reported at the NEXT DD as {@code
     * mismatched input 'DD' expecting JOB}. That is 40 of the 62 members the
     * corpus could not parse, all at the first such delimiter in the member.
     */
    @Test
    public void aDelimiterBetweenTwoDdsOfOneStepKeepsBothDds() {
        assertEquals(
                namesOf("IN", "OUT"),
                ddNames(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEFBR14",
                        "//IN       DD  DSN=A.B,DISP=SHR",
                        "/*",
                        "//OUT      DD  DSN=C.D,DISP=SHR"));
    }

    /** Continuation lines still fold across a delimiter that follows them. */
    @Test
    public void aDelimiterAfterAContinuedDdKeepsBothDds() {
        assertEquals(
                namesOf("IN", "OUT"),
                ddNames(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEFBR14",
                        "//IN       DD  DSN=A.B,",
                        "//             DISP=(NEW,CATLG),",
                        "//             SPACE=(CYL,(2,1),RLSE)",
                        "/*",
                        "//OUT      DD  DSN=C.D,DISP=SHR"));
    }

    /** More than one, because the fix has to loop rather than admit exactly one. */
    @Test
    public void everyDelimiterInOneStepsDdListIsAbsorbed() {
        assertEquals(
                namesOf("IN", "WORK", "OUT"),
                ddNames(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEFBR14",
                        "/*",
                        "//IN       DD  DSN=A.B,DISP=SHR",
                        "/*",
                        "//WORK     DD  DSN=&&T,DISP=(NEW,PASS)",
                        "/*",
                        "//OUT      DD  DSN=C.D,DISP=SHR",
                        "/*"));
    }

    /**
     * A step whose DD list holds BOTH kinds: a real in-stream-data terminator and
     * a delimiter terminating nothing. The first is consumed by the lexer in
     * DATA_MODE, the second reaches the parser.
     */
    @Test
    public void aStepMixingBothKindsOfDelimiterKeepsEveryDd() {
        assertEquals(
                namesOf("SYSIN", "OUT"),
                ddNames(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEBGENER",
                        "//SYSIN    DD *",
                        "  GENERATE MAXFLDS=1",
                        "/*",
                        "//OUT      DD  DSN=C.D,DISP=SHR",
                        "/*"));
    }

    /**
     * The third shape, past the two above: in-stream data that is EMPTY. {@code
     * //SYSIN DD *} immediately followed by {@code /*} says "this step gets an
     * empty SYSIN", and the corpus says it often.
     *
     * <p>{@code ddParmASTERISK_DATA} required {@code DD_ASTERISK_DATA+}, so with
     * no data lines the rule could not match, and the terminator the lexer had
     * already emitted in DATA_MODE had no rule left to consume it. That was not
     * reported as an error: {@code ddStatement} closes fine with zero
     * ddParmASTERISK_DATA, and {@code EOF} is optional in {@code execJCL}, so the
     * parse simply STOPPED at the terminator and returned the prefix it had. Every
     * step after the empty in-stream block vanished silently. On the production
     * corpus that cost 126 of 860 members 745 steps between them, one member
     * losing 69 of its 74.
     */
    @Test
    public void anEmptyInStreamDataBlockDoesNotEndTheJob() {
        assertEquals(
                2,
                steps(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEFBR14",
                        "//SYSIN    DD *",
                        "/*",
                        "//STEP2    EXEC PGM=IEFBR14"));
    }

    /** The empty block's own DD has to survive too, not just the steps after it. */
    @Test
    public void anEmptyInStreamDataBlockKeepsItsOwnDdAndTheNext() {
        assertEquals(
                namesOf("SYSIN", "OUT"),
                ddNames(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEFBR14",
                        "//SYSIN    DD *",
                        "/*",
                        "//OUT      DD  DSN=C.D,DISP=SHR"));
    }

    /**
     * A populated in-stream block followed by an empty one, which is how the shape
     * actually appears in the corpus: a real SYSTSIN, then {@code //SYSIN DD *}
     * with nothing under it.
     */
    @Test
    public void anEmptyInStreamBlockAfterAPopulatedOneDoesNotEndTheJob() {
        assertEquals(
                2,
                steps(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IKJEFT01",
                        "//SYSTSIN  DD *",
                        "  DSN SYSTEM(DSN)",
                        "  END",
                        "//SYSIN    DD *",
                        "/*",
                        "//STEP2    EXEC PGM=IEFBR14"));
    }

    /** An empty in-stream block at the very end of the job is still a valid job. */
    @Test
    public void anEmptyInStreamDataBlockAtTheEndOfTheJobIsAccepted() {
        assertEquals(
                1,
                steps(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEFBR14",
                        "//SYSIN    DD *",
                        "/*"));
    }

    /**
     * An empty in-stream block with no terminator at all -- the next {@code //}
     * card ends it. This shape already worked (DATA_MODE_TERMINATOR2 is consumed
     * by a different path), so it guards the fix against regressing it.
     */
    @Test
    public void anEmptyInStreamDataBlockWithNoTerminatorStillEndsAtTheNextCard() {
        assertEquals(
                2,
                steps(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEFBR14",
                        "//SYSIN    DD *",
                        "//STEP2    EXEC PGM=IEFBR14"));
    }

    /** A delimiter before the first step is a delimiter like any other. */
    @Test
    public void aDelimiterAheadOfEveryStepIsAbsorbed() {
        assertEquals(
                2,
                steps(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "/*",
                        "//STEP1    EXEC PGM=IEFBR14",
                        "/*",
                        "//STEP2    EXEC PGM=IEFBR14"));
    }
}
