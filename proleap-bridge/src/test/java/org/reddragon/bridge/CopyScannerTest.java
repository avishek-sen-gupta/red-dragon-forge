package org.reddragon.bridge;

import com.google.gson.Gson;
import com.google.gson.JsonObject;

import org.junit.Test;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.io.StringReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/**
 * COPY extraction with no copybook resolution.
 *
 * <p>Knowing which copybooks a corpus cannot resolve must not cost a full parse:
 * resolution is what fails, and it fails one program at a time after a JVM has
 * already built an ASG. ProLeap's {@code CobolPreprocessor.g4} recognises
 * {@code copyStatement} on its own, upstream of {@code CobolDocumentParserImpl}
 * where resolution lives, so the grammar answers the question without ever
 * touching a copybook directory.
 *
 * <p>Two properties matter more than the happy path:
 *
 * <ul>
 *   <li>An unterminated literal must not hide the COPYs after it. The grammar's
 *       STRINGLITERAL excludes newlines, so a quote left open by fixed-format
 *       continuation degrades to a TEXT token that charDataLine absorbs. A
 *       scanner whose string rule spans newlines instead pairs the opening quote
 *       with the continuation's resume quote and goes blind for the rest of the
 *       file.
 *   <li>A commented-out COPY must not be reported. The grammar's COMMENTLINE
 *       only matches free-format {@code *>}, so fixed-format column-7 indicators
 *       have to be blanked before the parse or a dead COPY reads as live.
 * </ul>
 */
public class CopyScannerTest {

    @Test
    public void aCopyReportsItsNameAndLine() {
        String source =
            "000100 IDENTIFICATION DIVISION.\n"
            + "000200 PROCEDURE DIVISION.\n"
            + "000300     COPY CUSTREC.\n";

        CopyScanner.ScanResult result = CopyScanner.scan("PROGA.cbl", source);

        assertEquals(List.of(new CopyScanner.CopyRef("CUSTREC", 3)), result.copies());
        assertEquals(0, result.errors());
    }

    @Test
    public void aCopyCommentedOutInColumnSevenIsNotReported() {
        String source =
            "000100 IDENTIFICATION DIVISION.\n"
            + "000200* COPY DEADBOOK.\n"
            + "000300     COPY LIVEBOOK.\n";

        CopyScanner.ScanResult result = CopyScanner.scan("PROGA.cbl", source);

        assertEquals(List.of(new CopyScanner.CopyRef("LIVEBOOK", 3)), result.copies());
    }

    @Test
    public void aCopyOnAPageEjectCommentLineIsNotReported() {
        String source = "000100/ COPY DEADBOOK.\n000200     COPY LIVEBOOK.\n";

        CopyScanner.ScanResult result = CopyScanner.scan("PROGA.cbl", source);

        assertEquals(List.of(new CopyScanner.CopyRef("LIVEBOOK", 2)), result.copies());
    }

    @Test
    public void anUnterminatedLiteralDoesNotHideALaterCopy() {
        // Column 7 '-' continues the literal opened on the line before, which the
        // raw source leaves unterminated. Everything after it must stay visible.
        String source =
            "000100     MOVE 'SERIAL N\n"
            + "000200-    'O' TO WS-FIELD.\n"
            + "000300     COPY CUSTREC.\n";

        CopyScanner.ScanResult result = CopyScanner.scan("PROGA.cbl", source);

        assertEquals(List.of(new CopyScanner.CopyRef("CUSTREC", 3)), result.copies());
    }

    @Test
    public void blankingACommentLineKeepsEveryLaterLineNumberIntact() {
        // Emptied, never removed: a dropped line shifts every reported COPY line
        // after it, and a line number nobody can trust is worse than none.
        String blanked = CopyScanner.blankCommentLines("000100* dead\n000200 live\n");

        assertEquals("\n000200 live\n", blanked);
    }

    @Test
    public void aLibraryQualifiedCopyReportsOnlyTheCopybookName() {
        // copySource is `(literal | cobolWord | filename) ((OF | IN) copyLibrary)?`,
        // and getText() concatenates children with no separator, so the whole
        // context would read "CUSTRECOFMYLIB" — a name that matches nothing on disk
        // and would be reported missing under a name the source never wrote.
        String source = "000100     COPY CUSTREC OF MYLIB.\n";

        CopyScanner.ScanResult result = CopyScanner.scan("PROGA.cbl", source);

        assertEquals(List.of(new CopyScanner.CopyRef("CUSTREC", 1)), result.copies());
    }

    @Test
    public void anInQualifiedCopyReportsOnlyTheCopybookName() {
        String source = "000100     COPY CUSTREC IN MYLIB.\n";

        CopyScanner.ScanResult result = CopyScanner.scan("PROGA.cbl", source);

        assertEquals(List.of(new CopyScanner.CopyRef("CUSTREC", 1)), result.copies());
    }

    @Test
    public void aLiteralCopyNameIsReportedWithoutItsQuotes() {
        // ProLeap resolves the literal form through LiteralCopyBookFinderImpl, on
        // the literal's content. Keeping the quotes would make every literal COPY
        // unresolvable by definition.
        String source = "000100     COPY 'CUSTREC.CPY'.\n";

        CopyScanner.ScanResult result = CopyScanner.scan("PROGA.cbl", source);

        assertEquals(
            List.of(new CopyScanner.CopyRef("CUSTREC.CPY", 1)), result.copies());
    }

    @Test
    public void aDoubleQuotedLiteralCopyNameIsAlsoUnquoted() {
        String source = "000100     COPY \"CUSTREC\".\n";

        CopyScanner.ScanResult result = CopyScanner.scan("PROGA.cbl", source);

        assertEquals(List.of(new CopyScanner.CopyRef("CUSTREC", 1)), result.copies());
    }

    @Test
    public void twoCopiesOfOneNameReportBothLines() {
        String source = "000100     COPY CUSTREC.\n000200 X.\n000300     COPY CUSTREC.\n";

        CopyScanner.ScanResult result = CopyScanner.scan("PROGA.cbl", source);

        assertEquals(
            List.of(
                new CopyScanner.CopyRef("CUSTREC", 1),
                new CopyScanner.CopyRef("CUSTREC", 3)),
            result.copies());
    }

    private static Path sourceFile(String name, String content) throws Exception {
        Path path = Files.createTempFile(name, ".cbl");
        path.toFile().deleteOnExit();
        Files.writeString(path, content);
        return path;
    }

    private static String[] runBatch(String stdin) {
        ByteArrayOutputStream captured = new ByteArrayOutputStream();
        CopyScanner.runBatch(
            new StringReader(stdin), new PrintStream(captured, true, StandardCharsets.UTF_8));
        return captured.toString(StandardCharsets.UTF_8).strip().split("\n");
    }

    @Test
    public void batchModeEmitsOneJsonLinePerPath() throws Exception {
        // One JSON object per line rather than one array: the corpus is thousands
        // of members, and the reader consumes them as they arrive instead of
        // holding the whole scan in memory before it can parse anything.
        Path first = sourceFile("first", "000100     COPY CUSTREC.\n");
        Path second = sourceFile("second", "000100 X.\n000200     COPY ORDREC.\n");

        String[] lines = runBatch(first + "\n" + second + "\n");

        assertEquals(2, lines.length);
        JsonObject one = new Gson().fromJson(lines[0], JsonObject.class);
        assertEquals(first.toString(), one.get("file").getAsString());
        assertEquals(0, one.get("errors").getAsInt());
        assertEquals(1, one.getAsJsonArray("copies").size());
        JsonObject copy = one.getAsJsonArray("copies").get(0).getAsJsonObject();
        assertEquals("CUSTREC", copy.get("name").getAsString());
        assertEquals(1, copy.get("line").getAsInt());

        JsonObject two = new Gson().fromJson(lines[1], JsonObject.class);
        assertEquals(
            "ORDREC",
            two.getAsJsonArray("copies").get(0).getAsJsonObject().get("name").getAsString());
        assertEquals(2, two.getAsJsonArray("copies").get(0).getAsJsonObject().get("line").getAsInt());
    }

    @Test
    public void anUnreadablePathDoesNotAbortTheRestOfTheBatch() throws Exception {
        // A batch is the whole corpus. One member that cannot be read is corpus
        // shape, and losing the other 3778 results to it would be a worse answer
        // than reporting it and moving on.
        Path readable = sourceFile("readable", "000100     COPY CUSTREC.\n");

        String[] lines = runBatch("/nonexistent/nope.cbl\n" + readable + "\n");

        assertEquals(2, lines.length);
        JsonObject failed = new Gson().fromJson(lines[0], JsonObject.class);
        assertEquals("/nonexistent/nope.cbl", failed.get("file").getAsString());
        assertTrue(failed.get("errors").getAsInt() > 0);
        assertEquals(0, failed.getAsJsonArray("copies").size());
        assertTrue(failed.has("message"));

        JsonObject ok = new Gson().fromJson(lines[1], JsonObject.class);
        assertEquals(1, ok.getAsJsonArray("copies").size());
    }

    @Test
    public void blankLinesInThePathListAreSkipped() throws Exception {
        Path only = sourceFile("only", "000100     COPY CUSTREC.\n");

        String[] lines = runBatch("\n" + only + "\n\n");

        assertEquals(1, lines.length);
        assertEquals(
            only.toString(),
            new Gson().fromJson(lines[0], JsonObject.class).get("file").getAsString());
    }
}
