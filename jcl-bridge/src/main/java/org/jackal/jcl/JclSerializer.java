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
 *             "sysout":     true|false,
 *             "dummy":      true|false
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
import java.util.stream.IntStream;

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

    /**
     * Parse JCL source and serialize it to the Jackal JCL JSON contract.
     *
     * <p>Split out of {@link #main} so the whole grammar-to-JSON path is
     * exercisable without stdin/stdout or a process exit: a test states a JCL
     * snippet and reads the JSON the Python side would receive.
     */
    static JsonObject serialize(String src) {
        JCLLexer lexer = new JCLLexer(CharStreams.fromString(src));
        CommonTokenStream tokens = new CommonTokenStream(lexer);
        JCLParser parser = new JCLParser(tokens);

        // Fail loud: collect syntax errors, throw if any.
        FailingErrorListener errs = new FailingErrorListener();
        lexer.removeErrorListeners();
        lexer.addErrorListener(errs);
        parser.removeErrorListeners();
        parser.addErrorListener(errs);

        ParseTree tree = parser.startRule();
        if (errs.hasErrors()) {
            throw new SyntaxErrorException(errs.text());
        }

        return new JobBuilder().build((JCLParser.StartRuleContext) tree);
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
                JCLParser.ProcJCLContext procJCL = findChild(jcl, JCLParser.ProcJCLContext.class);
                if (procJCL != null) {
                    return buildProcJCL(procJCL);
                }
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

        /**
         * Build the JSON for a bare PROC document (a .prc file: //NAME PROC
         * ... // PEND, no JOB card) — the grammar's procJCL alternative,
         * previously unhandled (build() fell through to the empty-job
         * fallback for it). Reuses buildStep for its steps, identically to
         * execJCL's own step handling.
         */
        private JsonObject buildProcJCL(JCLParser.ProcJCLContext ctx) {
            JsonObject proc = new JsonObject();

            JCLParser.ProcStatementContext procStmt =
                    findChild(ctx, JCLParser.ProcStatementContext.class);
            String procName = "";
            JsonObject defaults = new JsonObject();
            if (procStmt != null) {
                JCLParser.ProcNameContext nameCtx =
                        findChild(procStmt, JCLParser.ProcNameContext.class);
                if (nameCtx != null) {
                    procName = nameCtx.getText();
                }
                List<JCLParser.DefineSymbolicParameterContext> defs = new ArrayList<>();
                collectAll(procStmt, JCLParser.DefineSymbolicParameterContext.class, defs);
                for (JCLParser.DefineSymbolicParameterContext d : defs) {
                    String paramName = null;
                    JCLParser.KeywordOrSymbolicContext valueCtx = null;
                    for (int i = 0; i < d.getChildCount(); i++) {
                        ParseTree child = d.getChild(i);
                        if (child instanceof TerminalNode
                                && ((TerminalNode) child).getSymbol().getType()
                                        == JCLLexer.PROC_PARM_NAME) {
                            paramName = child.getText();
                        } else if (child instanceof JCLParser.KeywordOrSymbolicContext) {
                            valueCtx = (JCLParser.KeywordOrSymbolicContext) child;
                        }
                    }
                    if (paramName != null) {
                        defaults.add(
                                paramName,
                                valueCtx != null ? buildValueParts(valueCtx) : new JsonArray());
                    }
                }
            }
            proc.addProperty("name", procName);
            proc.add("defaults", defaults);

            JsonArray steps = new JsonArray();
            for (int i = 0; i < ctx.getChildCount(); i++) {
                ParseTree child = ctx.getChild(i);
                if (child instanceof JCLParser.JclStepContext) {
                    steps.add(buildStep((JCLParser.JclStepContext) child));
                }
            }
            proc.add("steps", steps);
            return proc;
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

            // PARM= on the EXEC statement
            JsonArray parmParts = new JsonArray();
            if (execStmt != null) {
                JCLParser.ExecParmPARMContext parmCtx =
                        findChild(execStmt, JCLParser.ExecParmPARMContext.class);
                if (parmCtx != null) {
                    JCLParser.KeywordOrSymbolicContext kwCtx =
                            findChild(parmCtx, JCLParser.KeywordOrSymbolicContext.class);
                    if (kwCtx != null) {
                        parmParts = buildValueParts(kwCtx);
                    }
                }
            }
            step.add("parm", parmParts);

            // PROC parm overrides (EXEC PROC=NAME,SYM=val,...) — execProcParm
            // children of execProcStatement, empty object for an ordinary
            // EXEC PGM= step or a PROC call with no overrides.
            JsonObject procParms = new JsonObject();
            if (execStmt != null) {
                JCLParser.ExecProcStatementContext procStmtCtx =
                        findChild(execStmt, JCLParser.ExecProcStatementContext.class);
                if (procStmtCtx != null) {
                    List<JCLParser.ExecProcParmContext> overrides = new ArrayList<>();
                    collectAll(procStmtCtx, JCLParser.ExecProcParmContext.class, overrides);
                    for (JCLParser.ExecProcParmContext o : overrides) {
                        String paramName = null;
                        JCLParser.KeywordOrSymbolicContext valueCtx = null;
                        for (int i = 0; i < o.getChildCount(); i++) {
                            ParseTree child = o.getChild(i);
                            if (child instanceof TerminalNode
                                    && ((TerminalNode) child).getSymbol().getType()
                                            == JCLLexer.EXEC_PROC_PARM) {
                                paramName = child.getText();
                            } else if (child instanceof JCLParser.KeywordOrSymbolicContext) {
                                valueCtx = (JCLParser.KeywordOrSymbolicContext) child;
                            }
                        }
                        if (paramName != null) {
                            procParms.add(
                                    paramName,
                                    valueCtx != null ? buildValueParts(valueCtx) : new JsonArray());
                        }
                    }
                }
            }
            step.add("proc_parms", procParms);

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
            // code: first word — a numeric return code. The mapa grammar guarantees
            // this slot is a number for a real condition, and COND=EVEN/ONLY is handled
            // separately (never reaches here), so parse directly: a non-numeric code
            // throws and fails the bridge loudly rather than silently defaulting to 0.
            obj.addProperty("code", Integer.parseInt(words.get(0)));
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
                empty.add("dsn", new JsonArray());
                empty.add("disp_words", new JsonArray());
                empty.add("in_stream", new JsonArray());
                empty.addProperty("sysout", false);
                empty.addProperty("dummy", false);
                return empty;
            }

            JsonObject dd = new JsonObject();

            // ddname
            JCLParser.DdNameContext ddNameCtx = findChild(ddStmt, JCLParser.DdNameContext.class);
            dd.addProperty("ddname", ddNameCtx != null ? ddNameCtx.getText() : "");

            // ddParameter list — fold each parameter into a new, immutable DdParamFields
            // rather than reassigning a bundle of local flags across the loop.
            DdParamFields fields = IntStream.range(0, ddStmt.getChildCount())
                    .mapToObj(ddStmt::getChild)
                    .filter(JCLParser.DdParameterContext.class::isInstance)
                    .map(JCLParser.DdParameterContext.class::cast)
                    .map(param -> param.getChild(0))
                    .reduce(DdParamFields.empty(), this::foldDdParameter, (a, b) -> b);

            JsonArray dsn = fields.dsn();
            JsonArray dispWords = fields.dispWords();
            boolean sysout = fields.sysout();
            boolean dummy = fields.dummy();
            boolean isAsterisk = fields.isAsterisk();
            if (fields.backref() != null) {
                dd.add("backref", fields.backref());
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

            dd.add("dsn", dsn);
            dd.add("disp_words", dispWords);
            dd.add("in_stream", inStream);
            dd.addProperty("sysout", sysout);
            dd.addProperty("dummy", dummy);
            return dd;
        }

        /** Immutable accumulator for one ddStatement's ddParameter children. */
        private record DdParamFields(
                JsonArray dsn,
                JsonArray dispWords,
                boolean sysout,
                boolean dummy,
                boolean isAsterisk,
                JsonObject backref) {

            static DdParamFields empty() {
                return new DdParamFields(new JsonArray(), new JsonArray(), false, false, false, null);
            }
        }

        /** Fold one ddParameter's inner context into a new DdParamFields. */
        private DdParamFields foldDdParameter(DdParamFields acc, ParseTree inner) {
            return switch (inner) {
                case JCLParser.DdParmDSNAMEContext dsnCtx -> foldDsname(acc, dsnCtx);
                case JCLParser.DdParmDISPContext dispCtx -> {
                    JCLParser.SingleOrMultipleValueContext val =
                            findChild(dispCtx, JCLParser.SingleOrMultipleValueContext.class);
                    yield val == null
                            ? acc
                            : new DdParamFields(
                                    acc.dsn(), extractWords(val), acc.sysout(), acc.dummy(),
                                    acc.isAsterisk(), acc.backref());
                }
                case JCLParser.DdParmSYSOUTContext c -> new DdParamFields(
                        acc.dsn(), acc.dispWords(), true, acc.dummy(), acc.isAsterisk(), acc.backref());
                case JCLParser.DdParmDUMMYContext c -> new DdParamFields(
                        acc.dsn(), acc.dispWords(), acc.sysout(), true, acc.isAsterisk(), acc.backref());
                case JCLParser.DdParmASTERISKContext c -> new DdParamFields(
                        acc.dsn(), acc.dispWords(), acc.sysout(), acc.dummy(), true, acc.backref());
                default -> acc;
            };
        }

        /** Fold a DSNAME parameter: a direct dataset name, or a two/three-segment backward reference. */
        private DdParamFields foldDsname(DdParamFields acc, JCLParser.DdParmDSNAMEContext dsnCtx) {
            JCLParser.DatasetNameContext datasetName =
                    findChild(dsnCtx, JCLParser.DatasetNameContext.class);
            if (datasetName == null) {
                return acc;
            }
            String raw = datasetName.getText();
            if (!raw.startsWith("*.")) {
                return new DdParamFields(
                        buildValueParts(datasetName), acc.dispWords(), acc.sysout(), acc.dummy(),
                        acc.isAsterisk(), acc.backref());
            }
            // backward reference: *.STEPNAME.DDNAME (two-segment) or longer
            String[] parts = raw.substring(2).split("\\.");
            if (parts.length != 2) {
                // three-segment or malformed — pass structured parts; Python raises ValueError
                return new DdParamFields(
                        buildValueParts(datasetName), acc.dispWords(), acc.sysout(), acc.dummy(),
                        acc.isAsterisk(), acc.backref());
            }
            JsonObject backref = new JsonObject();
            backref.addProperty("step", parts[0]);
            backref.addProperty("ddname", parts[1]);
            // leave dsn=[] — Python parser dispatches on "backref" key first
            return new DdParamFields(
                    new JsonArray(), acc.dispWords(), acc.sysout(), acc.dummy(), acc.isAsterisk(), backref);
        }

        /**
         * Extract the positional words of a singleOrMultipleValue context, keeping an
         * empty string for each omitted subparameter.
         *
         * <pre>
         *   SHR                  -> ["SHR"]
         *   (SHR)                -> ["SHR"]
         *   (NEW,CATLG,DELETE)   -> ["NEW","CATLG","DELETE"]
         *   (,PASS)              -> ["","PASS"]
         *   (NEW,,DELETE)        -> ["NEW","","DELETE"]
         * </pre>
         *
         * <p>Splits the context's terminals on COMMA instead of collecting its
         * keywordOrSymbolic children, because a keyword collection cannot express an
         * omitted slot: {@code (,PASS)} and {@code (PASS)} would both yield one word,
         * and {@code (NEW,,DELETE)} would silently read as {@code (NEW,DELETE)}. The
         * comma tokens are the only record of position.
         *
         * <p>Flattening to terminals also makes this independent of which
         * singleOrMultipleValue alternative the parser chose: {@code (,PASS)} matches
         * the parenList alternative and {@code (NEW,,DELETE)} does not, and the two
         * put their keywords at different depths.
         *
         * <p>DISP is the only caller. A value with nested parentheses or an embedded
         * equality (the PARM= shapes) would have its inner commas counted as
         * separators here; DISP cannot contain either.
         */
        private JsonArray extractWords(JCLParser.SingleOrMultipleValueContext ctx) {
            List<TerminalNode> terminals = new ArrayList<>();
            collectTerminals(ctx, terminals);

            List<String> slots = new ArrayList<>();
            StringBuilder current = new StringBuilder();
            for (TerminalNode t : terminals) {
                int type = t.getSymbol().getType();
                if (type == JCLParser.LPAREN || type == JCLParser.RPAREN) {
                    continue;
                }
                if (type == JCLParser.COMMA) {
                    slots.add(current.toString().trim());
                    current.setLength(0);
                    continue;
                }
                current.append(t.getText());
            }
            slots.add(current.toString().trim());

            JsonArray arr = new JsonArray();
            // A value with no subparameter at all (DISP=()) is absent, not one empty slot.
            if (slots.size() == 1 && slots.get(0).isEmpty()) {
                return arr;
            }
            slots.forEach(arr::add);
            return arr;
        }

        /** ctx's terminal nodes, depth-first, in source order. */
        private void collectTerminals(ParseTree node, List<TerminalNode> out) {
            if (node instanceof TerminalNode t) {
                out.add(t);
                return;
            }
            for (int i = 0; i < node.getChildCount(); i++) {
                collectTerminals(node.getChild(i), out);
            }
        }

        /**
         * Build an ordered list of {"type":"Symbol"|"Literal","name":...}
         * parts from a parse-tree node, classified by each terminal's own
         * lexer token type (JCLLexer.SYMBOLIC vs everything else) — never
         * inferred from text content. Hidden-channel tokens (e.g. the
         * apostrophes around a quoted PARM value) are not tree children and
         * so are naturally excluded — no separate stripping needed. Adjacent
         * non-SYMBOLIC terminals are merged into one Literal part.
         */
        private JsonArray buildValueParts(ParseTree ctx) {
            JsonArray parts = new JsonArray();
            StringBuilder literalRun = new StringBuilder();
            collectValueParts(ctx, parts, literalRun);
            flushLiteral(parts, literalRun);
            return parts;
        }

        private void collectValueParts(ParseTree node, JsonArray parts, StringBuilder literalRun) {
            if (node instanceof TerminalNode) {
                TerminalNode tn = (TerminalNode) node;
                int type = tn.getSymbol().getType();
                if (type == JCLLexer.SYMBOLIC) {
                    flushLiteral(parts, literalRun);
                    String text = tn.getText(); // e.g. "&CNTLLIB"
                    JsonObject part = new JsonObject();
                    part.addProperty("type", "Symbol");
                    part.addProperty("name", text.substring(1)); // strip leading '&'
                    parts.add(part);
                } else {
                    literalRun.append(tn.getText());
                }
                return;
            }
            for (int i = 0; i < node.getChildCount(); i++) {
                collectValueParts(node.getChild(i), parts, literalRun);
            }
        }

        private void flushLiteral(JsonArray parts, StringBuilder literalRun) {
            if (literalRun.length() > 0) {
                JsonObject part = new JsonObject();
                part.addProperty("type", "Literal");
                part.addProperty("name", literalRun.toString());
                parts.add(part);
                literalRun.setLength(0);
            }
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
