package org.jackal.jcl;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import org.junit.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.junit.Assert.assertEquals;

/**
 * DISP subparameter positions survive serialization.
 *
 * <p>{@code DISP=(status,normal,abnormal)} may omit any positional
 * subparameter. The parse tree records the omission as a bare COMMA with no
 * neighbouring keyword, so the serializer has to emit an empty slot rather than
 * a shorter list: the Python side reads {@code disp_words} by position, and a
 * list that closed up the gap says something the JCL did not.
 */
public class JclSerializerTest {

    /** A one-step job whose single DD carries the given DISP text. */
    private static List<String> dispWords(String ddParameters) {
        String jcl =
                "//TESTJOB  JOB (ACCT),CLASS=A\n"
                        + "//STEP1    EXEC PGM=IEFBR14\n"
                        + "//OUT      DD DSN=A.B.C" + ddParameters + "\n";
        JsonObject job = JclSerializer.serialize(jcl);
        JsonObject dd =
                job.getAsJsonArray("statements")
                        .get(0)
                        .getAsJsonObject()
                        .getAsJsonArray("dds")
                        .get(0)
                        .getAsJsonObject();
        JsonArray words = dd.getAsJsonArray("disp");
        List<String> result = new ArrayList<>();
        words.forEach(w -> result.add(w.getAsString()));
        return result;
    }

    @Test
    public void allThreeSubparametersAreKeptInOrder() {
        assertEquals(
                Arrays.asList("NEW", "CATLG", "DELETE"), dispWords(",DISP=(NEW,CATLG,DELETE)"));
    }

    @Test
    public void anUnparenthesizedStatusIsTheOnlyWord() {
        assertEquals(Arrays.asList("SHR"), dispWords(",DISP=SHR"));
    }

    @Test
    public void aParenthesizedStatusIsTheOnlyWord() {
        assertEquals(Arrays.asList("SHR"), dispWords(",DISP=(SHR)"));
    }

    @Test
    public void aDdWithNoDispHasNoWords() {
        assertEquals(Arrays.asList(), dispWords(""));
    }

    @Test
    public void anOmittedStatusLeavesAnEmptyLeadingSlot() {
        assertEquals(Arrays.asList("", "PASS"), dispWords(",DISP=(,PASS)"));
    }

    @Test
    public void anOmittedStatusIsKeptAheadOfBothDispositions() {
        assertEquals(Arrays.asList("", "CATLG", "DELETE"), dispWords(",DISP=(,CATLG,DELETE)"));
    }

    @Test
    public void anOmittedNormalDispositionDoesNotShiftTheAbnormalOneLeft() {
        assertEquals(Arrays.asList("NEW", "", "DELETE"), dispWords(",DISP=(NEW,,DELETE)"));
    }
}
