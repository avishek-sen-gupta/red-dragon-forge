package org.jackal.jcl;

import com.google.gson.JsonObject;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

/**
 * A bare {@code /*} between steps does not end the job.
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
