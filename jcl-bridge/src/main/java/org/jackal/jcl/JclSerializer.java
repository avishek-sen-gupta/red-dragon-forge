package org.jackal.jcl;

/*
 * Rule names discovered from the mapa ANTLR JCL grammar (cschneid-the-elder/mapa)
 * by reading JCLParser.g4 directly (the Python antlr4-tools runtime does not execute
 * the Java-specific embedded actions in JCLLexer.g4, so its tree output is unreliable).
 *
 * Key rules used:
 *   startRule -> jcl -> execJCL
 *   execJCL   -> jobCard -> jobName (NAME_FIELD token: the job name)
 *   execJCL   -> jclStep+ (one per EXEC statement)
 *   jclStep   -> execStatement -> execPgmStatement | execProcStatement
 *                  execPgmStatement:  SS stepName? EXEC PGM EQUAL keywordOrSymbolic execParameter*
 *                  execProcStatement: SS stepName? EXEC (PROC_EX EQUAL)? keywordOrSymbolic ...
 *   stepName  -> NAME_FIELD
 *   jclStep   -> ddStatementAmalgamation* (zero or more after the exec)
 *   ddStatementAmalgamation -> ddStatement ddStatementConcatenation*
 *   ddStatement:  SS ddName DD ddParameter* ddParmASTERISK_DATA*
 *   ddName:       (NAME | NAME_FIELD) (DOT (NAME | NAME_FIELD))?
 *   ddParameter alternatives used here:
 *     ddParmDSNAME:  (DSNAME | DSN) EQUAL datasetName
 *     ddParmDISP:    DISP EQUAL singleOrMultipleValue
 *     ddParmSYSOUT:  SYSOUT EQUAL singleOrMultipleValue
 *     ddParmASTERISK: ASTERISK  (marks DD * — in-stream data follows)
 *   ddParmASTERISK_DATA: DD_ASTERISK_DATA+ (DATA_MODE_TERMINATOR3 | DATA_MODE_TERMINATORX)?
 *
 * JSON contract emitted (field order irrelevant, Gson serialises alphabetically):
 *   {
 *     "name": "<jobname>",
 *     "steps": [
 *       {
 *         "name": "<stepname>",
 *         "pgm": "<pgm-or-proc>",
 *         "dds": [
 *           {
 *             "ddname":     "<ddname>",
 *             "dsn":        "<dataset-name or ''>",
 *             "disp_words": ["<word>", ...],
 *             "in_stream":  ["<line>", ...],
 *             "sysout":     true|false
 *           }
 *         ]
 *       }
 *     ]
 *   }
 */

import com.google.gson.*;
import org.antlr.v4.runtime.*;
import org.antlr.v4.runtime.tree.*;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

public final class JclSerializer {

    public static void main(String[] args) throws IOException {
        String src = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
        JCLLexer lexer = new JCLLexer(CharStreams.fromString(src));
        CommonTokenStream tokens = new CommonTokenStream(lexer);
        JCLParser parser = new JCLParser(tokens);

        // Fail loud: collect syntax errors, exit non-zero if any.
        FailingErrorListener errs = new FailingErrorListener();
        lexer.removeErrorListeners();
        lexer.addErrorListener(errs);
        parser.removeErrorListeners();
        parser.addErrorListener(errs);

        ParseTree tree = parser.startRule();
        if (errs.hasErrors()) {
            System.err.print(errs.text());
            System.exit(1);
        }

        JsonObject job = new JobBuilder().build((JCLParser.StartRuleContext) tree);
        System.out.print(new Gson().toJson(job));
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

    // -------------------------------------------------------------------------
    // JobBuilder — walks the parse tree and emits the JSON contract
    // -------------------------------------------------------------------------

    static final class JobBuilder {

        JsonObject build(JCLParser.StartRuleContext ctx) {
            JsonObject job = new JsonObject();

            // Locate the jcl > execJCL node
            JCLParser.JclContext jcl = findChild(ctx, JCLParser.JclContext.class);
            if (jcl == null) {
                job.addProperty("name", "");
                job.add("steps", new JsonArray());
                return job;
            }

            // execJCL can appear multiple times but we handle only the first job
            JCLParser.ExecJCLContext execJCL = findChild(jcl, JCLParser.ExecJCLContext.class);
            if (execJCL == null) {
                job.addProperty("name", "");
                job.add("steps", new JsonArray());
                return job;
            }

            // Job name
            JCLParser.JobCardContext jobCard = findChild(execJCL, JCLParser.JobCardContext.class);
            String jobName = "";
            if (jobCard != null) {
                JCLParser.JobNameContext jobNameCtx = findChild(jobCard, JCLParser.JobNameContext.class);
                if (jobNameCtx != null) {
                    jobName = jobNameCtx.getText();
                }
            }
            job.addProperty("name", jobName);

            // Steps — each jclStep child of execJCL
            JsonArray steps = new JsonArray();
            for (int i = 0; i < execJCL.getChildCount(); i++) {
                ParseTree child = execJCL.getChild(i);
                if (child instanceof JCLParser.JclStepContext) {
                    steps.add(buildStep((JCLParser.JclStepContext) child));
                }
            }
            job.add("steps", steps);
            return job;
        }

        private JsonObject buildStep(JCLParser.JclStepContext ctx) {
            JsonObject step = new JsonObject();

            // execStatement -> execPgmStatement | execProcStatement
            JCLParser.ExecStatementContext execStmt =
                    findChild(ctx, JCLParser.ExecStatementContext.class);

            String stepName = "";
            String pgm = "";

            if (execStmt != null) {
                JCLParser.ExecPgmStatementContext pgmStmt =
                        findChild(execStmt, JCLParser.ExecPgmStatementContext.class);
                JCLParser.ExecProcStatementContext procStmt =
                        findChild(execStmt, JCLParser.ExecProcStatementContext.class);

                if (pgmStmt != null) {
                    JCLParser.StepNameContext sn = findChild(pgmStmt, JCLParser.StepNameContext.class);
                    if (sn != null) stepName = sn.getText();
                    JCLParser.KeywordOrSymbolicContext kw =
                            findChild(pgmStmt, JCLParser.KeywordOrSymbolicContext.class);
                    if (kw != null) pgm = kw.getText();
                } else if (procStmt != null) {
                    JCLParser.StepNameContext sn = findChild(procStmt, JCLParser.StepNameContext.class);
                    if (sn != null) stepName = sn.getText();
                    JCLParser.KeywordOrSymbolicContext kw =
                            findChild(procStmt, JCLParser.KeywordOrSymbolicContext.class);
                    if (kw != null) pgm = kw.getText();
                }
            }

            step.addProperty("name", stepName);
            step.addProperty("pgm", pgm);

            // DD statements — ddStatementAmalgamation children of jclStep
            JsonArray dds = new JsonArray();
            for (int i = 0; i < ctx.getChildCount(); i++) {
                ParseTree child = ctx.getChild(i);
                if (child instanceof JCLParser.DdStatementAmalgamationContext) {
                    dds.add(buildDd((JCLParser.DdStatementAmalgamationContext) child));
                }
            }
            step.add("dds", dds);
            return step;
        }

        private JsonObject buildDd(JCLParser.DdStatementAmalgamationContext ctx) {
            // The primary ddStatement is the first child
            JCLParser.DdStatementContext ddStmt = findChild(ctx, JCLParser.DdStatementContext.class);
            if (ddStmt == null) {
                JsonObject empty = new JsonObject();
                empty.addProperty("ddname", "");
                empty.addProperty("dsn", "");
                empty.add("disp_words", new JsonArray());
                empty.add("in_stream", new JsonArray());
                empty.addProperty("sysout", false);
                return empty;
            }

            JsonObject dd = new JsonObject();

            // ddname
            JCLParser.DdNameContext ddNameCtx = findChild(ddStmt, JCLParser.DdNameContext.class);
            dd.addProperty("ddname", ddNameCtx != null ? ddNameCtx.getText() : "");

            // ddParameter list
            String dsn = "";
            JsonArray dispWords = new JsonArray();
            boolean sysout = false;
            boolean isAsterisk = false;

            for (int i = 0; i < ddStmt.getChildCount(); i++) {
                ParseTree child = ddStmt.getChild(i);
                if (child instanceof JCLParser.DdParameterContext) {
                    JCLParser.DdParameterContext param = (JCLParser.DdParameterContext) child;
                    ParseTree inner = param.getChild(0);

                    if (inner instanceof JCLParser.DdParmDSNAMEContext) {
                        JCLParser.DdParmDSNAMEContext dsnCtx = (JCLParser.DdParmDSNAMEContext) inner;
                        JCLParser.DatasetNameContext datasetName =
                                findChild(dsnCtx, JCLParser.DatasetNameContext.class);
                        if (datasetName != null) {
                            dsn = datasetName.getText();
                        }
                    } else if (inner instanceof JCLParser.DdParmDISPContext) {
                        JCLParser.DdParmDISPContext dispCtx = (JCLParser.DdParmDISPContext) inner;
                        JCLParser.SingleOrMultipleValueContext val =
                                findChild(dispCtx, JCLParser.SingleOrMultipleValueContext.class);
                        if (val != null) {
                            dispWords = extractWords(val);
                        }
                    } else if (inner instanceof JCLParser.DdParmSYSOUTContext) {
                        sysout = true;
                    } else if (inner instanceof JCLParser.DdParmASTERISKContext) {
                        isAsterisk = true;
                    }
                }
            }

            // in-stream data — ddParmASTERISK_DATA children
            // Only collect DD_ASTERISK_DATA terminal tokens; skip DATA_MODE_TERMINATOR3/X.
            JsonArray inStream = new JsonArray();
            if (isAsterisk) {
                for (int i = 0; i < ddStmt.getChildCount(); i++) {
                    ParseTree child = ddStmt.getChild(i);
                    if (child instanceof JCLParser.DdParmASTERISK_DATAContext) {
                        JCLParser.DdParmASTERISK_DATAContext dataCtx =
                                (JCLParser.DdParmASTERISK_DATAContext) child;
                        // Collect only DD_ASTERISK_DATA terminal tokens (not terminators)
                        StringBuilder rawData = new StringBuilder();
                        for (int j = 0; j < dataCtx.getChildCount(); j++) {
                            ParseTree tok = dataCtx.getChild(j);
                            if (tok instanceof TerminalNode) {
                                TerminalNode tn = (TerminalNode) tok;
                                int tokenType = tn.getSymbol().getType();
                                if (tokenType == JCLLexer.DD_ASTERISK_DATA) {
                                    rawData.append(tn.getText());
                                }
                                // Skip DATA_MODE_TERMINATOR3 and DATA_MODE_TERMINATORX
                            }
                        }
                        // Split on newlines; keep each physical line as in Lark output
                        String raw = rawData.toString();
                        // Strip a single trailing newline that precedes the /* terminator
                        if (raw.endsWith("\n")) {
                            raw = raw.substring(0, raw.length() - 1);
                        } else if (raw.endsWith("\r\n")) {
                            raw = raw.substring(0, raw.length() - 2);
                        }
                        String[] lines = raw.split("\n", -1);
                        for (String line : lines) {
                            // Strip trailing carriage returns (Windows line endings)
                            String cleaned = line.endsWith("\r")
                                    ? line.substring(0, line.length() - 1)
                                    : line;
                            inStream.add(cleaned);
                        }
                    }
                }
            }

            dd.addProperty("dsn", dsn);
            dd.add("disp_words", dispWords);
            dd.add("in_stream", inStream);
            dd.addProperty("sysout", sysout);
            return dd;
        }

        /**
         * Extract the individual keyword words from a singleOrMultipleValue context.
         * For plain SHR -> ["SHR"]
         * For (NEW,CATLG,DELETE) -> ["NEW","CATLG","DELETE"]
         */
        private JsonArray extractWords(JCLParser.SingleOrMultipleValueContext ctx) {
            JsonArray arr = new JsonArray();
            // Collect all keywordOrSymbolic children, which carry the actual word text
            List<JCLParser.KeywordOrSymbolicContext> kwList = new ArrayList<>();
            collectAll(ctx, JCLParser.KeywordOrSymbolicContext.class, kwList);
            for (JCLParser.KeywordOrSymbolicContext kw : kwList) {
                String word = kw.getText().trim();
                if (!word.isEmpty()) {
                    arr.add(word);
                }
            }
            return arr;
        }

        // ----------------------------------------------------------------
        // Generic tree helpers
        // ----------------------------------------------------------------

        /** Find the first direct or indirect child of the given type. */
        @SuppressWarnings("unchecked")
        private static <T extends ParseTree> T findChild(ParseTree node, Class<T> type) {
            for (int i = 0; i < node.getChildCount(); i++) {
                ParseTree child = node.getChild(i);
                if (type.isInstance(child)) return (T) child;
                T found = findChild(child, type);
                if (found != null) return found;
            }
            return null;
        }

        /** Collect ALL descendants of the given type into the list. */
        @SuppressWarnings("unchecked")
        private static <T extends ParseTree> void collectAll(
                ParseTree node, Class<T> type, List<T> out) {
            for (int i = 0; i < node.getChildCount(); i++) {
                ParseTree child = node.getChild(i);
                if (type.isInstance(child)) out.add((T) child);
                collectAll(child, type, out);
            }
        }
    }
}
