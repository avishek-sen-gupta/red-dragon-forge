package org.jackal.jcl;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;

/**
 * A parse that cannot consume the whole member says so.
 *
 * <p>{@code startRule} used to read {@code jcl | EOF}, and {@code execJCL} /
 * {@code procJCL} end in {@code EOF?}. Nothing required the parser to reach the
 * end of its input, so a member whose tail no rule could match still produced a
 * tree for the PREFIX, with zero syntax errors. The parser had no way to report
 * "I stopped at line 40 of 300" and the serializer had no way to ask.
 *
 * <p>The shape that reaches it: a trailing {@code //} null statement is matched
 * by {@code SS?} in {@code jcl}, and it leaves the lexer in DATA_MODE. Any
 * following card that does not itself start with {@code //} then lexes as a
 * {@code DD_ASTERISK_DATA} token with no rule left to consume it. On one
 * production corpus that was 27 of 860 members, every one of them carrying a
 * lone {@code 0x1A} transfer artifact -- so the fix is two parts: anchor
 * {@code EOF} so leftover input is an error, and drop the artifact ahead of the
 * lexer so those 27 members are not failed over a byte that is not theirs.
 *
 * <p>Measured on the same corpus before the anchor: 29 further members consumed
 * only a prefix, 7218 source lines matched by nothing, zero errors reported.
 * Those were caused by a separate grammar defect (see {@link
 * DelimiterStatementTest}); the anchor is what would have made them loud.
 */
public class EndOfInputTest {

    /** Ctrl-Z, written as an escape so the source file holds no control character. */
    private static final String END_OF_FILE_MARKER = "\u001A";

    private static JsonObject job(String... lines) {
        return JclSerializer.serialize(String.join("\n", lines) + "\n");
    }

    private static int steps(String... lines) {
        return job(lines).getAsJsonArray("steps").size();
    }

    /** The in-stream lines of the first step's first DD. */
    private static JsonArray inStream(String... lines) {
        return job(lines).getAsJsonArray("steps").get(0).getAsJsonObject()
                .getAsJsonArray("dds").get(0).getAsJsonObject()
                .getAsJsonArray("in_stream");
    }

    private static JsonArray linesOf(String... values) {
        JsonArray expected = new JsonArray();
        for (String value : values) {
            expected.add(value);
        }
        return expected;
    }

    /**
     * The corpus shape, whole: in-stream data, its delimiter, a null statement,
     * then the transfer artifact. Every step has to survive it.
     */
    @Test
    public void aTrailingEndOfFileMarkerAfterANullStatementKeepsTheWholeMember() {
        assertEquals(
                2,
                steps(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEBGENER",
                        "//SYSIN    DD  *",
                        "  GENERATE MAXFLDS=1",
                        "/*",
                        "//STEP2    EXEC PGM=IEFBR14",
                        "//",
                        END_OF_FILE_MARKER));
    }

    /** The same, with no in-stream data anywhere: the null statement is enough. */
    @Test
    public void aTrailingEndOfFileMarkerAfterANullStatementNeedsNoInStreamData() {
        assertEquals(
                1,
                steps(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEFBR14",
                        "//WORK     DD  DUMMY",
                        "//",
                        END_OF_FILE_MARKER));
    }

    /** No null statement either -- the marker is dropped wherever it ends the file. */
    @Test
    public void aTrailingEndOfFileMarkerWithNoNullStatementIsDroppedToo() {
        assertEquals(
                1,
                steps(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEFBR14",
                        END_OF_FILE_MARKER));
    }

    /** The artifact must not be absorbed into the data it follows. */
    @Test
    public void aTrailingEndOfFileMarkerDoesNotJoinTheInStreamData() {
        assertEquals(
                linesOf("  GENERATE MAXFLDS=1"),
                inStream(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEBGENER",
                        "//SYSIN    DD  *",
                        "  GENERATE MAXFLDS=1",
                        "/*",
                        "//",
                        END_OF_FILE_MARKER));
    }

    /**
     * The strip is scoped to end of input, so a marker byte INSIDE an in-stream
     * data block stays what it is: data.
     */
    @Test
    public void aMarkerInsideInStreamDataIsKeptAsData() {
        assertEquals(
                2,
                steps(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEBGENER",
                        "//SYSIN    DD  *",
                        "  GENERATE" + END_OF_FILE_MARKER + "MAXFLDS=1",
                        "/*",
                        "//STEP2    EXEC PGM=IEFBR14"));
    }

    /**
     * The general case of the same hole, with no artifact in it: a plain card
     * after the null statement. It used to vanish -- 11 tokens matched by
     * nothing, zero errors, the member reported as parsed. Now it is reported.
     */
    @Test
    public void aCardAfterTheNullStatementIsReportedInsteadOfDropped() {
        assertThrows(
                JclSerializer.SyntaxErrorException.class,
                () -> steps(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEFBR14",
                        "//WORK     DD  DUMMY",
                        "//",
                        "JUNK CARD"));
    }

    /** Two markers are not the measured artifact, so the second is reported. */
    @Test
    public void aSecondEndOfFileMarkerIsReportedRatherThanAssumed() {
        assertThrows(
                JclSerializer.SyntaxErrorException.class,
                () -> steps(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEFBR14",
                        "//",
                        END_OF_FILE_MARKER,
                        END_OF_FILE_MARKER));
    }

    /**
     * A card that DOES start with {@code //} after the null statement was always
     * consumed, because {@code //} takes the lexer back out of DATA_MODE. The
     * anchor must not start rejecting it.
     */
    @Test
    public void aStepAfterTheNullStatementStillParses() {
        assertEquals(
                2,
                steps(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEFBR14",
                        "//",
                        "//STEP2    EXEC PGM=IEFBR14"));
    }

    /** Same guard, for a whole second JOB card after the null statement. */
    @Test
    public void aSecondJobCardAfterTheNullStatementStillParses() {
        assertEquals(
                2,
                steps(
                        "//JOBONE   JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEFBR14",
                        "//",
                        "//JOBTWO   JOB (ACCT),CLASS=A",
                        "//STEP2    EXEC PGM=IEFBR14"));
    }

    /** A member that just ends at its null statement, with nothing after it. */
    @Test
    public void aMemberEndingAtItsNullStatementParses() {
        assertEquals(
                1,
                steps(
                        "//TESTJOB  JOB (ACCT),CLASS=A",
                        "//STEP1    EXEC PGM=IEFBR14",
                        "//"));
    }
}
