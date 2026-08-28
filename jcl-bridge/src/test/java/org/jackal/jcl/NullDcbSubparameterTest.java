package org.jackal.jcl;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import org.junit.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.junit.Assert.assertEquals;

/**
 * A DCB keyword subparameter may be coded with a null value: {@code
 * DCB=(RECFM=FB,LRECL=2000,BLKSIZE=)}.
 *
 * <p>The lexer already allowed this, on purpose -- KYWD_VAL_MODE carries
 * KYWD_VAL_COMMA and KYWD_VAL_RPAREN precisely so that {@code DATACLAS=} and
 * {@code COPIES=,} lex, and its comment says so. Only the parser rule disagreed:
 * {@code ddParmBLKSIZE} required a {@code keywordOrSymbolic} where {@code
 * ddParmDATACLAS} had long since made it optional. So the fix is that grammar's
 * existing idiom for a nullable keyword, applied to one more rule.
 *
 * <p>Whether z/OS itself accepts the form is not settled here and does not need
 * to be. cobble records no block size at all -- JclSerializer emits no DCB, and
 * BLKSIZE appears nowhere in the Python -- so accepting a null one invents
 * nothing and discards nothing. Rejecting it cost two members of the onboarding
 * corpus every DD edge they had, to enforce a rule about a field that is parsed
 * and thrown away. The evidence says the cards are a dropped {@code 0}: three
 * occurrences against 2193 {@code BLKSIZE=0} corpus-wide, in two members that
 * write {@code BLKSIZE=0} themselves. A typo in a discarded field is still not a
 * reason to lose the job.
 *
 * <p>Only BLKSIZE is loosened, not {@code keywordOrSymbolic} itself. A null
 * {@code DSN=} would be a real loss -- cobble builds dataset edges out of it --
 * so the value stays required everywhere the value is used.
 */
public class NullDcbSubparameterTest {

    /** The job's only DD, so the parameters around the DCB can be read off it. */
    private static JsonObject onlyDd(String... ddLines) {
        return onlyDdOfCards(false, ddLines);
    }

    /**
     * The same, with every card blank-padded to 80 columns the way the corpus
     * members are: a different lexer path, and the one the real cards take.
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

    private static List<String> stringsOf(JsonArray array) {
        List<String> result = new ArrayList<>();
        array.forEach(element -> result.add(element.getAsString()));
        return result;
    }

    private static String literalDsn(JsonObject dd) {
        JsonArray parts = dd.getAsJsonArray("dsn");
        assertEquals("expected a single value part", 1, parts.size());
        return parts.get(0).getAsJsonObject().get("name").getAsString();
    }

    /**
     * A null BLKSIZE last in the list, so the empty value is followed by the
     * closing paren. The DISP is the assertion that matters: it can only be read
     * back if the statement parsed as one DD.
     */
    @Test
    public void aNullBlksizeLastInTheDcbListParses() {
        JsonObject dd =
                onlyDd(
                        "//OUT      DD  DSN=A.B,",
                        "//             DCB=(RECFM=FB,LRECL=2000,BLKSIZE=),",
                        "//             DISP=(NEW,CATLG)");
        assertEquals("A.B", literalDsn(dd));
        assertEquals(Arrays.asList("NEW", "CATLG"), stringsOf(dd.getAsJsonArray("disp_words")));
    }

    /**
     * A null BLKSIZE followed by another subparameter, so the empty value is
     * followed by a comma instead -- KYWD_VAL_COMMA rather than
     * KYWD_VAL_RPAREN, a separate lexer path.
     */
    @Test
    public void aNullBlksizeFollowedByAnotherSubparameterParses() {
        JsonObject dd =
                onlyDd(
                        "//OUT      DD  DSN=A.B,",
                        "//             DCB=(BLKSIZE=,LRECL=80,RECFM=FB),",
                        "//             DISP=(NEW,CATLG)");
        assertEquals(Arrays.asList("NEW", "CATLG"), stringsOf(dd.getAsJsonArray("disp_words")));
    }

    /**
     * The shape the production corpus actually holds: 80-column cards, the DCB
     * mid-statement, SPACE continuing after it.
     */
    @Test
    public void aNullBlksizeParsesFromPaddedCards() {
        JsonObject dd =
                onlyDdOfPaddedCards(
                        "//SORTOUT  DD DSN=A.B,DISP=(NEW,PASS),",
                        "//        UNIT=(SYSDA,3),DCB=(RECFM=FB,LRECL=2000,BLKSIZE=),",
                        "//        SPACE=(CYL,(250,50),RLSE)");
        assertEquals("A.B", literalDsn(dd));
        assertEquals(Arrays.asList("NEW", "PASS"), stringsOf(dd.getAsJsonArray("disp_words")));
    }

    /**
     * The form the same members use everywhere else, and the one the null cards
     * were almost certainly meant to be. It must keep working.
     */
    @Test
    public void anExplicitZeroBlksizeStillParses() {
        JsonObject dd =
                onlyDd(
                        "//OUT      DD  DSN=A.B,",
                        "//             DCB=(BLKSIZE=0,LRECL=3300,RECFM=FB),",
                        "//             DISP=(NEW,CATLG)");
        assertEquals(Arrays.asList("NEW", "CATLG"), stringsOf(dd.getAsJsonArray("disp_words")));
    }

    /** An ordinary numeric BLKSIZE, the case the required value was there for. */
    @Test
    public void anOrdinaryNumericBlksizeStillParses() {
        JsonObject dd =
                onlyDd(
                        "//OUT      DD  DSN=A.B,",
                        "//             DCB=(RECFM=FB,LRECL=80,BLKSIZE=27920),",
                        "//             DISP=(NEW,CATLG)");
        assertEquals(Arrays.asList("NEW", "CATLG"), stringsOf(dd.getAsJsonArray("disp_words")));
    }
}
