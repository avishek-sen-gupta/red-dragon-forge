package org.jackal.jcl;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import org.junit.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.junit.Assert.assertEquals;

/**
 * A {@code DCB=} whose value is a bare value -- a backward reference {@code
 * *.ddname} or a model dataset name -- may be continued onto the next line, like
 * every other DD parameter.
 *
 * <p>{@code DCB=} puts the lexer in {@code DCB_MODE}. A parenthesised DCB
 * switches to {@code KYWD_VAL_MODE}, which carries the comma-continuation rules
 * and so always folded correctly. A bare value does not switch modes: it is
 * consumed by {@code DCB_KEYWORD_VALUE}, and the comma after it by {@code
 * DCB_COMMA}, whose {@code ->more,popMode} swallows the comma into the next
 * token and leaves the lexer in {@code DD_PARM_MODE} looking at a naked newline.
 * That matched {@code DD_NEWLINE} and ended the statement, so the continuation
 * line began a new one -- surfacing as {@code no viable alternative} against its
 * first parameter.
 *
 * <p>DCB_MODE needed the same {@code ,\n} rule KYWD_VAL_MODE already had. It has
 * to use {@code mode()} rather than {@code pushMode()}, because the {@code
 * popMode} that ends the continuation in {@code COMMA_NEWLINE_MODE} has to land
 * back in {@code DD_PARM_MODE}.
 */
public class DcbContinuationTest {

    /** The job's only DD, so what the continuation line contributed can be read off it. */
    private static JsonObject onlyDd(String... ddLines) {
        return onlyDdOfCards(false, ddLines);
    }

    /**
     * The same, with every card blank-padded to 80 columns the way a member
     * punched from cards is: the comma that continues a statement is then
     * followed by blanks rather than by the newline directly.
     */
    private static JsonObject onlyDdOfPaddedCards(String... ddLines) {
        return onlyDdOfCards(true, ddLines);
    }

    private static JsonObject onlyDdOfCards(boolean padded, String... ddLines) {
        List<String> lines = new ArrayList<>();
        lines.add("//TESTJOB  JOB (ACCT),CLASS=A");
        lines.add("//STEP1    EXEC PGM=IEFBR14");
        lines.addAll(Arrays.asList(ddLines));
        if (padded) {
            lines.replaceAll(line -> line + " ".repeat(80 - line.length()));
        }
        JsonObject job = JclSerializer.serialize(String.join("\n", lines) + "\n");
        JsonArray steps = job.getAsJsonArray("steps");
        assertEquals("expected exactly one step", 1, steps.size());
        JsonArray dds = steps.get(0).getAsJsonObject().getAsJsonArray("dds");
        assertEquals("expected exactly one DD", 1, dds.size());
        return dds.get(0).getAsJsonObject();
    }

    /** {@code disp_words} is a plain list of words. */
    private static List<String> stringsOf(JsonArray array) {
        List<String> result = new ArrayList<>();
        array.forEach(element -> result.add(element.getAsString()));
        return result;
    }

    /** {@code dsn} is a list of value parts, each a literal run or a symbol. */
    private static String literalDsn(JsonObject dd) {
        JsonArray parts = dd.getAsJsonArray("dsn");
        assertEquals("expected a single value part", 1, parts.size());
        return parts.get(0).getAsJsonObject().get("name").getAsString();
    }

    /**
     * A parameter AFTER the DCB is the assertion that matters: it can only be
     * read back if the continuation folded into this DD instead of starting a
     * statement of its own.
     */
    @Test
    public void aBackwardReferenceDcbMayBeContinued() {
        JsonObject dd =
                onlyDd(
                        "//OUT      DD  DSN=A.B,",
                        "//             DCB=*.SORTIN,",
                        "//             DISP=(NEW,CATLG)");
        assertEquals("A.B", literalDsn(dd));
        assertEquals(Arrays.asList("NEW", "CATLG"), stringsOf(dd.getAsJsonArray("disp_words")));
    }

    /** The three-segment form of the same backward reference. */
    @Test
    public void aThreeSegmentBackwardReferenceDcbMayBeContinued() {
        JsonObject dd =
                onlyDd(
                        "//OUT      DD  DSN=A.B,",
                        "//             DCB=*.STEP0.PROCSTEP.SORTIN,",
                        "//             DISP=(NEW,CATLG)");
        assertEquals(Arrays.asList("NEW", "CATLG"), stringsOf(dd.getAsJsonArray("disp_words")));
    }

    /**
     * The other bare DCB value: a model dataset whose attributes are copied.
     * Same lexer path, so the fix has to cover it too.
     */
    @Test
    public void aModelDatasetNameDcbMayBeContinued() {
        JsonObject dd =
                onlyDd(
                        "//OUT      DD  DSN=A.B,",
                        "//             DCB=C.D,",
                        "//             DISP=(NEW,CATLG)");
        assertEquals(Arrays.asList("NEW", "CATLG"), stringsOf(dd.getAsJsonArray("disp_words")));
    }

    /**
     * The shape the production corpus actually holds: cards padded to 80
     * columns, so the continuing comma is followed by blanks. That is a
     * different lexer path from a bare {@code ,\n} -- KYWD_VAL_MODE needs both
     * KYWD_VAL_COMMA_NEWLINE and KYWD_VAL_COMMA_WS -- and it is the one that
     * cost a member.
     */
    @Test
    public void aBackwardReferenceDcbMayBeContinuedFromAPaddedCard() {
        JsonObject dd =
                onlyDdOfPaddedCards(
                        "//OUT      DD  DSN=A.B,",
                        "//            DCB=*.SORTIN,",
                        "//            SPACE=(TRK,(50,10),RLSE),",
                        "//            DISP=(NEW,CATLG)");
        assertEquals("A.B", literalDsn(dd));
        assertEquals(Arrays.asList("NEW", "CATLG"), stringsOf(dd.getAsJsonArray("disp_words")));
    }

    /** The model-dataset form of the same padded card. */
    @Test
    public void aModelDatasetNameDcbMayBeContinuedFromAPaddedCard() {
        JsonObject dd =
                onlyDdOfPaddedCards(
                        "//OUT      DD  DSN=A.B,",
                        "//            DCB=C.D,",
                        "//            DISP=(NEW,CATLG)");
        assertEquals(Arrays.asList("NEW", "CATLG"), stringsOf(dd.getAsJsonArray("disp_words")));
    }

    /** A padded card whose DCB is the last parameter continues nothing. */
    @Test
    public void aBackwardReferenceDcbLastOnAPaddedCardStillParses() {
        JsonObject dd =
                onlyDdOfPaddedCards(
                        "//OUT      DD  DSN=A.B,DISP=(NEW,CATLG),",
                        "//            DCB=*.SORTIN");
        assertEquals(Arrays.asList("NEW", "CATLG"), stringsOf(dd.getAsJsonArray("disp_words")));
    }

    /** The shape that always worked: nothing follows the DCB, so nothing continues. */
    @Test
    public void aBackwardReferenceDcbLastOnItsLineStillParses() {
        JsonObject dd =
                onlyDd(
                        "//OUT      DD  DSN=A.B,DISP=(NEW,CATLG),",
                        "//             DCB=*.SORTIN");
        assertEquals(Arrays.asList("NEW", "CATLG"), stringsOf(dd.getAsJsonArray("disp_words")));
    }

    /**
     * A keyword-subparameter DCB reaches the continuation through {@code
     * KYWD_VAL_MODE} instead, which is the path the new rule copies -- so it has
     * to keep working unchanged.
     */
    @Test
    public void aKeywordSubparameterDcbStillContinues() {
        JsonObject dd =
                onlyDd(
                        "//OUT      DD  DSN=A.B,",
                        "//             DCB=(RECFM=FB,LRECL=80),",
                        "//             DISP=(NEW,CATLG)");
        assertEquals(Arrays.asList("NEW", "CATLG"), stringsOf(dd.getAsJsonArray("disp_words")));
    }

    /** A comma-newline inside the DCB's own parenthesised list. */
    @Test
    public void aKeywordSubparameterDcbMayBreakInsideItsOwnParentheses() {
        JsonObject dd =
                onlyDd(
                        "//OUT      DD  DSN=A.B,",
                        "//             DCB=(RECFM=FB,",
                        "//             LRECL=80),",
                        "//             DISP=(NEW,CATLG)");
        assertEquals(Arrays.asList("NEW", "CATLG"), stringsOf(dd.getAsJsonArray("disp_words")));
    }
}
