package org.jackal.jcl;

import com.google.gson.*;
import org.antlr.v4.runtime.*;
import org.antlr.v4.runtime.atn.PredictionMode;
import org.antlr.v4.runtime.misc.ParseCancellationException;
import org.antlr.v4.runtime.tree.*;

import java.io.*;
import java.nio.charset.StandardCharsets;

/** Parses JCL with the mapa grammar and writes the JSON contract read by jackal.jcl.wire. */
public final class JclSerializer {

    public static void main(String[] args) throws IOException {
        String src = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
        JsonObject job;
        try {
            job = serialize(src);
        } catch (SyntaxErrorException e) {
            System.err.print(e.getMessage());
            System.exit(1);
            return;
        }
        System.out.print(new Gson().toJson(job));
    }

    /** Thrown when the grammar rejects the source; carries the collected error text. */
    static final class SyntaxErrorException extends RuntimeException {
        SyntaxErrorException(String text) {
            super(text);
        }
    }

    /** DOS/CP-M end-of-file marker, Ctrl-Z. Not a JCL character. */
    private static final char END_OF_FILE_MARKER = '\u001A';

    /**
     * Drop a single trailing {@code 0x1A} at end of input, with any whitespace
     * after it.
     *
     * <p>Members downloaded from a mainframe in binary mode can carry one: 27 of
     * the 860 in one production corpus end with a lone {@code 0x1A} on its own
     * line. It is a transfer artifact, not source, and no JCL rule can consume
     * it -- the lexer is in DATA_MODE at end of input, so it comes out as a
     * {@code DD_ASTERISK_DATA} token that nothing matches.
     *
     * <p>That was invisible while {@code EOF} was optional in {@code startRule}:
     * the parse returned the prefix and reported nothing. Anchoring {@code EOF}
     * turns leftover input into a syntax error, which is the point -- but it
     * would fail those 27 members over a byte that is not theirs. So the byte is
     * removed here, ahead of the lexer, and every OTHER kind of leftover is now
     * reported.
     *
     * <p>Scoped to end of input on purpose. A {@code 0x1A} inside an in-stream
     * data block is data and is left alone.
     */
    private static String withoutEndOfFileMarker(String src) {
        int end = src.length();
        while (end > 0 && Character.isWhitespace(src.charAt(end - 1))) {
            end--;
        }
        if (end == 0 || src.charAt(end - 1) != END_OF_FILE_MARKER) {
            return src;
        }
        return src.substring(0, end - 1);
    }

    /**
     * Parse JCL source and serialize it to the Jackal JCL JSON contract.
     *
     * <p>Split out of {@link #main} so the whole grammar-to-JSON path is
     * exercisable without stdin/stdout or a process exit: a test states a JCL
     * snippet and reads the JSON the Python side would receive.
     *
     * <p>Two-stage parse (the pattern from ANTLR's own TestPerformance): SLL
     * prediction with {@link BailErrorStrategy} first, full LL only if that
     * bails. {@code jcl : (execJCL+ SS?) | (procJCL SS?)} makes the top-level
     * alternative decidable only from deep in the member, so under the default
     * full-context LL prediction the cost grows superlinearly with input size --
     * measured at roughly O(n^1.8): 2.0s for a 10 KB member, 25.7s for 46 KB,
     * minutes for the largest. SLL decides the same alternatives without the
     * full-context work whenever the input is unambiguous, which is every member
     * that is valid JCL.
     *
     * <p>The LL stage is configured exactly as the single-stage parse was, so a
     * member SLL cannot decide gets the same tree and the same error text as
     * before: this changes how long a parse takes, never what it returns.
     */
    static JsonObject serialize(String src) {
        JCLLexer lexer = new JCLLexer(CharStreams.fromString(withoutEndOfFileMarker(src)));
        CommonTokenStream tokens = new CommonTokenStream(lexer);
        JCLParser parser = new JCLParser(tokens);

        // Fail loud: collect syntax errors, throw if any. The lexer's listener
        // stays attached across both stages -- a bad character is not something
        // SLL can bail out of, and the token stream is lexed once, so this
        // collects each lexer error exactly once however the parse goes.
        FailingErrorListener errs = new FailingErrorListener();
        lexer.removeErrorListeners();
        lexer.addErrorListener(errs);
        parser.removeErrorListeners();

        ParseTree tree = parseTwoStage(parser, tokens, errs);
        if (errs.hasErrors()) {
            throw new SyntaxErrorException(errs.text());
        }

        return new DocumentBuilder().build((JCLParser.StartRuleContext) tree);
    }

    /**
     * startRule() under SLL, falling back to full LL if SLL cannot decide.
     *
     * <p>No parser error listener during the SLL stage: BailErrorStrategy throws
     * on the first error rather than reporting it, so anything SLL rejects must
     * be re-parsed under LL before it can be called a syntax error. Reporting it
     * here would put a spurious error in {@code errs} for input LL accepts.
     */
    private static ParseTree parseTwoStage(
            JCLParser parser, CommonTokenStream tokens, FailingErrorListener errs) {
        parser.getInterpreter().setPredictionMode(PredictionMode.SLL);
        parser.setErrorHandler(new BailErrorStrategy());
        try {
            return parser.startRule();
        } catch (ParseCancellationException e) {
            tokens.seek(0);
            parser.reset();
            parser.getInterpreter().setPredictionMode(PredictionMode.LL);
            parser.setErrorHandler(new DefaultErrorStrategy());
            parser.addErrorListener(errs);
            return parser.startRule();
        }
    }

    // -------------------------------------------------------------------------
    // FailingErrorListener
    // -------------------------------------------------------------------------

    static final class FailingErrorListener extends BaseErrorListener {
        private final StringBuilder buf = new StringBuilder();

        @Override
        public void syntaxError(Recognizer<?, ?> recognizer,
                                Object offendingSymbol,
                                int line, int charPositionInLine,
                                String msg,
                                RecognitionException e) {
            buf.append("line ").append(line)
               .append(':').append(charPositionInLine)
               .append(' ').append(msg).append('\n');
        }

        boolean hasErrors() { return buf.length() > 0; }
        String text()       { return buf.toString(); }
    }
}
