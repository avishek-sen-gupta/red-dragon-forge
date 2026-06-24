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
 * COND rules (discovered 2024-06 from JCLParser.g4 + generated JCLParser.java):
 *   execParmCOND : EXEC_COND EQUAL (
 *       keywordOrSymbolic |                   <- EVEN / ONLY
 *       (LPAREN? (COMMA? LPAREN? keywordOrSymbolic (COMMA keywordOrSymbolic)* RPAREN?)+ RPAREN?)
 *     ) ;
 *   jobParmCOND  : COND EQUAL ((LPAREN parenList RPAREN) | parenList) ;
 *   parenList    : LPAREN COMMA* keywordOrSymbolic (COMMA+ keywordOrSymbolic)* RPAREN ;
 *
 *   ExecParmCONDContext.keywordOrSymbolic() returns ALL keyword children in order.
 *   Grouping algorithm for exec COND: walk children in sequence; an inner LPAREN starts
 *   a new condition group, RPAREN closes it. At depth 1 (outer paren), keywords are
 *   grouped per inner-paren group. Keyword order within a group: 0=code, 1=op, 2=step.
 *   For EVEN/ONLY (no parens at all), emit {"code":0,"op":"EVEN"|"ONLY","step":""}.
 *
 * JSON contract emitted (field order irrelevant, Gson serialises alphabetically):
 *   {
 *     "name": "<jobname>",
 *     "cond": [{"code":int,"op":str,"step":str}],   // job-level COND (may be absent)
 *     "steps": [
 *       {
 *         "name": "<stepname>",
 *         "pgm": "<pgm-or-proc>",
 *         "cond": [{"code":int,"op":str,"step":str}], // step-level COND (may be absent)
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

            // Job-level COND= on the JOB card
            if (jobCard != null) {
                JCLParser.JobParmCONDContext jobCondCtx =
                        findChild(jobCard, JCLParser.JobParmCONDContext.class);
                if (jobCondCtx != null) {
                    job.add("cond", buildJobCond(jobCondCtx));
                }
            }

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

            // COND= on the EXEC statement — find execParmCOND via execParameter children
            JsonArray condArray = new JsonArray();
            if (execStmt != null) {
                JCLParser.ExecParmCONDContext condCtx =
                        findChild(execStmt, JCLParser.ExecParmCONDContext.class);
                if (condCtx != null) {
                    condArray = buildExecCond(condCtx);
                }
            }
            step.add("cond", condArray);

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

        /**
         * Build the JSON "cond" array from an execParmCOND context.
         *
         * The grammar rule is flat (no sub-rule per condition tuple); we walk
         * children in order, using LPAREN/RPAREN terminals to track depth and
         * group keywords into individual (code, op[, step]) tuples.
         *
         * Depth accounting:
         *   - Outer paren (depth 0→1): outer wrapper, not a condition group.
         *   - Inner paren (depth 1→2) or no-inner-paren (depth 1, single condition):
         *     each inner group is one condition.
         *
         * For COND=EVEN / COND=ONLY (no parens, single keywordOrSymbolic):
         *   emit {"code":0,"op":"EVEN"|"ONLY","step":""}.
         */
        private JsonArray buildExecCond(JCLParser.ExecParmCONDContext ctx) {
            JsonArray arr = new JsonArray();

            // Walk children in order, noting LPAREN/RPAREN
            // Strategy: collect (token-type, text) for each direct/indirect terminal child,
            // but only direct children of ctx (not recursive — the rule is flat).
            // ExecParmCONDContext has: EXEC_COND, EQUAL, then the COND value children.

            // We need the children AFTER EXEC_COND and EQUAL.
            // Walk direct children of ctx in order; classify each terminal.
            int depth = 0;
            List<String> currentGroup = new ArrayList<>();
            boolean hasOuterParen = false;

            for (int i = 0; i < ctx.getChildCount(); i++) {
                ParseTree child = ctx.getChild(i);
                if (child instanceof TerminalNode) {
                    TerminalNode tn = (TerminalNode) child;
                    int type = tn.getSymbol().getType();
                    if (type == JCLParser.EXEC_COND || type == JCLParser.EQUAL) continue;
                    if (type == JCLParser.LPAREN) {
                        depth++;
                        if (depth == 1) { hasOuterParen = true; }
                        // depth > 1: start of an inner group
                    } else if (type == JCLParser.RPAREN) {
                        if (depth == 2) {
                            // closing inner group — flush current group as a condition
                            if (!currentGroup.isEmpty()) {
                                arr.add(condFromWords(currentGroup));
                                currentGroup.clear();
                            }
                        }
                        depth--;
                    } else if (type == JCLParser.COMMA) {
                        // commas separate values within a group; handled by keyword collection
                    }
                } else if (child instanceof JCLParser.KeywordOrSymbolicContext) {
                    String text = child.getText().trim().toUpperCase();
                    currentGroup.add(text);
                }
            }

            // If there are leftover words in currentGroup (single-condition with outer paren,
            // or no-paren EVEN/ONLY case):
            if (!currentGroup.isEmpty()) {
                if (!hasOuterParen) {
                    // EVEN / ONLY: single keyword, no parens — keyword goes in op slot, code=0
                    JsonObject obj = new JsonObject();
                    obj.addProperty("code", 0);
                    obj.addProperty("op", currentGroup.get(0).toUpperCase());
                    obj.addProperty("step", "");
                    arr.add(obj);
                } else if (arr.isEmpty()) {
                    // Single condition like (0,NE) or (0,NE,A)
                    arr.add(condFromWords(currentGroup));
                }
            }

            return arr;
        }

        /**
         * Build the JSON "cond" array from a jobParmCOND context.
         * Grammar: COND EQUAL ((LPAREN parenList RPAREN) | parenList)
         * parenList: LPAREN COMMA* keywordOrSymbolic (COMMA+ keywordOrSymbolic)* RPAREN
         * The keywords in a parenList are (code, op[, step]).
         * Multiple conditions are encoded as ((code,op),(code,op,...)) — two nested parenLists.
         */
        private JsonArray buildJobCond(JCLParser.JobParmCONDContext ctx) {
            JsonArray arr = new JsonArray();
            // Collect all parenList children
            List<JCLParser.ParenListContext> parenLists = new ArrayList<>();
            collectAll(ctx, JCLParser.ParenListContext.class, parenLists);

            if (parenLists.isEmpty()) return arr;

            // If there's exactly one parenList, it's a single condition: (code,op[,step])
            // If there are multiple parenLists, each is one condition tuple.
            // Heuristic: check depth. If the first parenList contains nested parenLists → multi.
            // Since collectAll recurses, parenLists may contain both outer + inner.
            // We only want the innermost (non-nested) ones.
            List<JCLParser.ParenListContext> leaves = new ArrayList<>();
            for (JCLParser.ParenListContext pl : parenLists) {
                List<JCLParser.ParenListContext> nested = new ArrayList<>();
                collectAll(pl, JCLParser.ParenListContext.class, nested);
                if (nested.isEmpty()) {
                    leaves.add(pl);
                }
            }

            if (leaves.isEmpty()) {
                // Fallback: use all
                leaves = parenLists;
            }

            for (JCLParser.ParenListContext pl : leaves) {
                List<JCLParser.KeywordOrSymbolicContext> kws = new ArrayList<>();
                collectAll(pl, JCLParser.KeywordOrSymbolicContext.class, kws);
                List<String> wordTexts = new ArrayList<>();
                for (JCLParser.KeywordOrSymbolicContext kw : kws) {
                    wordTexts.add(kw.getText().trim().toUpperCase());
                }
                if (!wordTexts.isEmpty()) {
                    arr.add(condFromWords(wordTexts));
                }
            }

            return arr;
        }

        /** Build a single COND JSON object from ordered word list [code, op] or [code, op, step]. */
        private JsonObject condFromWords(List<String> words) {
            JsonObject obj = new JsonObject();
            // code: first word (integer string)
            int code = 0;
            if (!words.isEmpty()) {
                try { code = Integer.parseInt(words.get(0)); } catch (NumberFormatException e) { /* 0 */ }
            }
            obj.addProperty("code", code);
            // op: second word (GT/GE/EQ/NE/LT/LE or EVEN/ONLY)
            String op = words.size() > 1 ? words.get(1).toUpperCase() : "";
            obj.addProperty("op", op);
            // step: third word if present, else ""
            String step = words.size() > 2 ? words.get(2) : "";
            obj.addProperty("step", step);
            return obj;
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
