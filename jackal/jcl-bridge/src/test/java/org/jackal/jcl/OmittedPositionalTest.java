package org.jackal.jcl;

import com.google.gson.JsonObject;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

/**
 * A subparameter list may omit its LAST positional, not only its first and middle
 * ones.
 *
 * <p>JCL lets a positional subparameter be omitted by leaving its position empty,
 * and {@code parenList} already allowed that leading ({@code DISP=(,PASS)}) and in
 * the middle ({@code SPACE=(CYL,(2,,2),RLSE)}) -- but it required a value after
 * the last comma, so {@code SPACE=(CYL,(2,2,),RLSE)} and {@code UNIT=(SYSDA,3,)}
 * did not parse. That is an inconsistency in the rule rather than a deliberate
 * strictness, and it cost 4 of the 8 members the production corpus could not
 * parse, all of them on a SORT step's SORTOUT DD.
 *
 * <p>The failure surfaced as {@code no viable alternative} reported against the
 * enclosing step's EXEC line, which is why these took bisection to find: the
 * position ANTLR prints is where {@code jclStep} started, not where the parse
 * actually died.
 */
public class OmittedPositionalTest {

    /** The DD parameter text of the job's only DD, round-tripped through the parse. */
    private static JsonObject onlyDd(String ddParameters) {
        String src =
                String.join(
                                "\n",
                                "//TESTJOB  JOB (ACCT),CLASS=A",
                                "//STEP1    EXEC PGM=IEFBR14",
                                "//OUT      DD  DSN=A.B," + ddParameters)
                        + "\n";
        JsonObject job = JclSerializer.serialize(src);
        return job.getAsJsonArray("steps")
                .get(0)
                .getAsJsonObject()
                .getAsJsonArray("dds")
                .get(0)
                .getAsJsonObject();
    }

    /** A DD that parses at all is the whole assertion: these are parse-shape tests. */
    private static void parses(String ddParameters) {
        assertEquals("OUT", onlyDd(ddParameters).get("ddname").getAsString());
    }

    @Test
    public void aTrailingOmittedPositionalInANestedSublistParses() {
        parses("SPACE=(CYL,(2,2,),RLSE)");
    }

    @Test
    public void aNestedSublistEndingInAnOmittedPositionalParses() {
        parses("SPACE=(CYL,(2,2,))");
    }

    @Test
    public void aTrailingOmittedPositionalInAFlatListParses() {
        parses("UNIT=(SYSDA,3,)");
    }

    /**
     * The three positions together, because a fix that only handles the last one
     * would leave the rule as inconsistent as it started.
     */
    @Test
    public void leadingAndMiddleOmissionsStillParse() {
        parses("DISP=(,PASS)");
        parses("SPACE=(CYL,(2,,2),RLSE)");
    }

    /** Nothing above should have loosened the ordinary forms. */
    @Test
    public void listsWithNoOmissionsStillParse() {
        parses("SPACE=(CYL,(2,2),RLSE)");
        parses("UNIT=(SYSDA,3)");
        parses("DISP=(NEW,CATLG,DELETE)");
    }
}
