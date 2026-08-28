package org.jackal.jcl;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/**
 * A {@code PROC} statement with no parameters may still carry a sequence number
 * in columns 73-80.
 *
 * <p>Columns 73-80 of a JCL statement are the identification/sequence field. The
 * system ignores them, and card-era members carry a line number there. It is not
 * a comment field: IBM allows a comment only on a statement that has a parameter
 * field, so {@code //NAME PROC} with nothing after it genuinely cannot take a
 * comment -- which is why this has to key on the column, not on absorbing
 * trailing text.
 *
 * <p>{@code PROC_MODE}'s {@code PROC_WS} assumed a parameter field always
 * follows the whitespace and switched to {@code PROC_PARM_MODE}, where the
 * sequence digits arrived as a {@code PROC_PARM_NAME} with no {@code =} after
 * it: {@code mismatched input '0' expecting {COMMENT_FLAG, SS}}. A {@code PROC}
 * WITH parameters escaped it only by accident -- the {@code =} pushes {@code
 * PROC_PARM_VALUE_MODE}, which absorbs the trailing field already.
 */
public class ProcSequenceNumberTest {

    /** The statement with {@code sequence} placed in columns 73-80, 1-based. */
    private static String withSequenceNumber(String statement, String sequence) {
        int sequenceField = 72; // column 73, 0-based
        assertTrue("statement already reaches the sequence field", statement.length() <= sequenceField);
        return statement + " ".repeat(sequenceField - statement.length()) + sequence;
    }

    /** The one literal part of a symbolic parameter's default value. */
    private static String literalValue(JsonObject defaults, String parameter) {
        JsonArray parts = defaults.getAsJsonArray(parameter);
        assertEquals("expected a single value part for " + parameter, 1, parts.size());
        return parts.get(0).getAsJsonObject().get("name").getAsString();
    }

    /** The JSON for a bare PROC member: {@code //NAME PROC ... // PEND}, no JOB card. */
    private static JsonObject proc(String... lines) {
        return JclSerializer.serialize(String.join("\n", lines) + "\n");
    }

    @Test
    public void aProcWithNoParametersMayCarryASequenceNumber() {
        JsonObject proc =
                proc(
                        withSequenceNumber("//TESTPROC PROC", "00010000"),
                        "//STEP1    EXEC PGM=IEFBR14",
                        "//         PEND");
        assertEquals("TESTPROC", proc.get("name").getAsString());
        assertEquals(0, proc.getAsJsonObject("defaults").size());
        assertEquals(1, proc.getAsJsonArray("steps").size());
    }

    /** A sequence number shorter than the full eight columns. */
    @Test
    public void aShortSequenceNumberIsAlsoIgnored() {
        JsonObject proc =
                proc(
                        withSequenceNumber("//TESTPROC PROC", "0000"),
                        "//STEP1    EXEC PGM=IEFBR14",
                        "//         PEND");
        assertEquals("TESTPROC", proc.get("name").getAsString());
        assertEquals(1, proc.getAsJsonArray("steps").size());
    }

    /** The shape that always worked: no sequence field at all. */
    @Test
    public void aProcWithNoParametersAndNoSequenceNumberStillParses() {
        JsonObject proc =
                proc("//TESTPROC PROC", "//STEP1    EXEC PGM=IEFBR14", "//         PEND");
        assertEquals("TESTPROC", proc.get("name").getAsString());
        assertEquals(0, proc.getAsJsonObject("defaults").size());
        assertEquals(1, proc.getAsJsonArray("steps").size());
    }

    /**
     * The other shape that already worked, and the one the parameter defaults
     * have to survive: the sequence field must not be read as a parameter.
     */
    @Test
    public void aProcWithParametersKeepsThemAlongsideASequenceNumber() {
        JsonObject proc =
                proc(
                        withSequenceNumber("//TESTPROC PROC MEMBER=A,LIB=B", "00010000"),
                        "//STEP1    EXEC PGM=IEFBR14",
                        "//         PEND");
        assertEquals("TESTPROC", proc.get("name").getAsString());
        JsonObject defaults = proc.getAsJsonObject("defaults");
        assertEquals(2, defaults.size());
        assertEquals("A", literalValue(defaults, "MEMBER"));
        assertEquals("B", literalValue(defaults, "LIB"));
        assertEquals(1, proc.getAsJsonArray("steps").size());
    }
}
