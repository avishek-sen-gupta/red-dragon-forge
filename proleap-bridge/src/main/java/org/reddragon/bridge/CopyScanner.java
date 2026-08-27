package org.reddragon.bridge;

import io.proleap.cobol.CobolPreprocessorBaseListener;
import io.proleap.cobol.CobolPreprocessorLexer;
import io.proleap.cobol.CobolPreprocessorParser;

import com.google.gson.Gson;

import org.antlr.v4.runtime.BaseErrorListener;
import org.antlr.v4.runtime.CharStreams;
import org.antlr.v4.runtime.CommonTokenStream;
import org.antlr.v4.runtime.RecognitionException;
import org.antlr.v4.runtime.Recognizer;
import org.antlr.v4.runtime.tree.ParseTree;
import org.antlr.v4.runtime.tree.ParseTreeWalker;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.PrintStream;
import java.io.Reader;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/**
 * The COPY statements a COBOL source names, without resolving any of them.
 *
 * <p>ProLeap splits preprocessing into {@code readLines} / {@code rewriteLines} /
 * {@code parseDocument} (see {@code CobolPreprocessorImpl}), and COPY resolution
 * lives only in the last of those, inside {@code CobolDocumentParserImpl}. The
 * {@code CobolPreprocessor.g4} grammar recognises {@code copyStatement} by
 * itself, so parsing with it alone answers "what does this corpus ask for"
 * without ever reading a copybook directory — which is the whole point, because
 * resolution is the step that fails and it fails only after a full ASG parse.
 *
 * <p>The grammar is also error-tolerant in the way this needs. Its STRINGLITERAL
 * excludes newlines, so a quote left unterminated by fixed-format continuation
 * degrades to a TEXT token that {@code charDataLine} absorbs and the parse walks
 * on. A scanner whose string rule spans newlines instead pairs the opening quote
 * with the continuation line's resume quote, and every COPY after that point in
 * the file becomes invisible.
 *
 * <p>What the grammar does not do is fixed-format comments: its COMMENTLINE rule
 * matches only free-format {@code *>}, so a column-7 {@code *} or {@code /} line
 * holding a commented-out COPY parses as a live one. Those lines are blanked here
 * first. cobble applies the same rule in Python for its own COPY/CALL scanner;
 * the duplication is three lines and buys a single file read per program.
 */
public final class CopyScanner {

    /** One COPY statement: the name as written, and the line it starts on. */
    public record CopyRef(String name, int line) {}

    /**
     * One scanned source. {@code errors} is the count of lexer and parser syntax
     * errors; it is not fatal, because ANTLR recovers and keeps reporting COPYs
     * after one. A non-zero count means this file's list may be incomplete.
     *
     * <p>{@code message} is null for anything that parsed, and is left out of the
     * JSON entirely by Gson's default null handling. It carries the reason a
     * member could not be read at all.
     */
    public record ScanResult(String file, int errors, List<CopyRef> copies, String message) {}

    private CopyScanner() {
        // prevent instantiation
    }

    /**
     * Empties fixed-format comment lines, keeping the line count identical.
     *
     * <p>Emptied rather than removed: dropping a line shifts every COPY line
     * reported after it, and the line number is the whole reason this is more
     * useful than a name.
     */
    static String blankCommentLines(String source) {
        String[] lines = source.split("\n", -1);
        for (int i = 0; i < lines.length; i++) {
            String line = lines[i];
            boolean fixedFormatComment =
                line.length() > 6 && (line.charAt(6) == '*' || line.charAt(6) == '/');
            if (fixedFormatComment || line.stripLeading().startsWith("*>")) {
                lines[i] = "";
            }
        }
        return String.join("\n", lines);
    }

    static ScanResult scan(String file, String source) {
        CobolPreprocessorLexer lexer =
            new CobolPreprocessorLexer(CharStreams.fromString(blankCommentLines(source)));
        CobolPreprocessorParser parser =
            new CobolPreprocessorParser(new CommonTokenStream(lexer));

        int[] errors = {0};
        BaseErrorListener counter = new BaseErrorListener() {
            @Override
            public void syntaxError(
                    Recognizer<?, ?> recognizer,
                    Object offendingSymbol,
                    int line,
                    int charPositionInLine,
                    String msg,
                    RecognitionException e) {
                errors[0]++;
            }
        };
        lexer.removeErrorListeners();
        lexer.addErrorListener(counter);
        parser.removeErrorListeners();
        parser.addErrorListener(counter);

        List<CopyRef> copies = new ArrayList<>();
        ParseTree tree = parser.startRule();
        new ParseTreeWalker().walk(new CobolPreprocessorBaseListener() {
            @Override
            public void enterCopyStatement(CobolPreprocessorParser.CopyStatementContext ctx) {
                copies.add(new CopyRef(copyName(ctx.copySource()), ctx.getStart().getLine()));
            }
        }, tree);

        return new ScanResult(file, errors[0], copies, null);
    }

    /**
     * Scans one path, reporting a read failure as a result rather than throwing.
     *
     * <p>Decoded with replacement, matching what cobble's own reader does: a
     * corpus member carrying a byte that is not valid UTF-8 still has COPY
     * statements worth reporting, and losing them to one bad byte would be the
     * wrong trade.
     */
    static ScanResult scanPath(String path) {
        try {
            byte[] bytes = Files.readAllBytes(Path.of(path));
            return scan(path, new String(bytes, StandardCharsets.UTF_8));
        } catch (IOException | RuntimeException e) {
            return new ScanResult(
                path, 1, List.of(), e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }

    /**
     * Scans every path read from {@code pathsIn}, one JSON object per output line.
     *
     * <p>JSON Lines rather than one array: a corpus is thousands of members, and
     * the reader consumes each result as it arrives instead of waiting for the
     * whole scan to serialise before it can parse anything. One JVM handles the
     * whole batch, which is the reason this is a batch at all — per-member JVM
     * startup dominates everything else the scan does.
     */
    public static void runBatch(Reader pathsIn, PrintStream out) {
        Gson gson = new Gson();
        try (BufferedReader reader = new BufferedReader(pathsIn)) {
            String line;
            while ((line = reader.readLine()) != null) {
                String path = line.strip();
                if (path.isEmpty()) {
                    continue;
                }
                out.println(gson.toJson(scanPath(path)));
            }
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    /**
     * The copybook name a {@code copySource} names, and nothing else.
     *
     * <p>The rule is {@code (literal | cobolWord | filename) ((OF | IN)
     * copyLibrary)?} and {@code getText()} concatenates children with no
     * separator, so the context as a whole reads "CUSTRECOFMYLIB" for
     * {@code COPY CUSTREC OF MYLIB} — a name the source never wrote, which would
     * be reported missing however well the real copybook resolves. Only the first
     * alternative is the name.
     */
    private static String copyName(CobolPreprocessorParser.CopySourceContext ctx) {
        if (ctx.literal() != null) {
            return unquote(ctx.literal().getText());
        }
        if (ctx.cobolWord() != null) {
            return ctx.cobolWord().getText();
        }
        if (ctx.filename() != null) {
            return ctx.filename().getText();
        }
        return ctx.getText();
    }

    /**
     * Strips a matching pair of surrounding quotes.
     *
     * <p>ProLeap resolves the literal form through {@code LiteralCopyBookFinderImpl}
     * on the literal's content, so a quoted name kept quoted could never resolve.
     */
    private static String unquote(String text) {
        if (text.length() >= 2) {
            char first = text.charAt(0);
            boolean quoted = (first == '\'' || first == '"')
                && text.charAt(text.length() - 1) == first;
            if (quoted) {
                return text.substring(1, text.length() - 1);
            }
        }
        return text;
    }
}
