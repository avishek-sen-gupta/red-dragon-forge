package org.jackal.jcl;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.antlr.v4.runtime.tree.ParseTree;
import org.antlr.v4.runtime.tree.TerminalNode;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.Optional;

/** A job or PROC document: its statements in order, with IF blocks nesting the statements between them. */
final class DocumentBuilder {

    private static final class OpenIf {
        final JsonObject block = new JsonObject();
        final JsonArray then = new JsonArray();
        final JsonArray otherwise = new JsonArray();
        boolean inElse;

        OpenIf(JCLParser.IfStatementContext ctx) {
            block.addProperty("kind", "if");
            block.addProperty("label", Trees.token(ctx, JCLParser.NAME_FIELD).map(TerminalNode::getText).orElse(""));
            block.add("condition", IfExpressionReader.read(ctx));
        }

        void enterElse() {
            if (inElse) {
                throw new JclSerializer.SyntaxErrorException("ELSE twice in one IF");
            }
            inElse = true;
        }

        JsonArray current() {
            return inElse ? otherwise : then;
        }

        JsonObject close() {
            block.add("then", then);
            block.add("otherwise", otherwise);
            return block;
        }
    }

    JsonObject build(JCLParser.StartRuleContext ctx) {
        Optional<JCLParser.JclContext> jcl = Trees.first(ctx, JCLParser.JclContext.class);
        Optional<JCLParser.ExecJCLContext> execJCL = jcl.flatMap(j -> Trees.first(j, JCLParser.ExecJCLContext.class));
        if (execJCL.isPresent()) {
            return job(execJCL.get());
        }
        return jcl.flatMap(j -> Trees.first(j, JCLParser.ProcJCLContext.class))
                .map(this::proc)
                .orElseGet(this::emptyJob);
    }

    private JsonObject emptyJob() {
        JsonObject job = new JsonObject();
        job.addProperty("kind", "job");
        job.addProperty("name", "");
        job.add("end_job_tests", new JsonArray());
        job.add("statements", new JsonArray());
        return job;
    }

    private JsonObject job(JCLParser.ExecJCLContext ctx) {
        Optional<JCLParser.JobCardContext> card = Trees.first(ctx, JCLParser.JobCardContext.class);
        JsonObject job = new JsonObject();
        job.addProperty("kind", "job");
        job.addProperty("name", card.flatMap(c -> Trees.first(c, JCLParser.JobNameContext.class))
                .map(ParseTree::getText).orElse(""));
        job.add("end_job_tests", card.flatMap(c -> Trees.first(c, JCLParser.JobParmCONDContext.class))
                .map(ConditionReader::endJobTests).orElseGet(JsonArray::new));
        job.add("statements", jobStatements(Trees.children(ctx)));
        return job;
    }

    private JsonObject proc(JCLParser.ProcJCLContext ctx) {
        return proc(Trees.first(ctx, JCLParser.ProcStatementContext.class), Trees.children(ctx));
    }

    /** A job's statements, with each in-stream PROC ... PEND gathered into one procedure definition. */
    private JsonArray jobStatements(List<ParseTree> children) {
        List<Piece> outside = new ArrayList<>();
        int at = 0;
        while (at < children.size()) {
            ParseTree child = children.get(at);
            if (child instanceof JCLParser.PendStatementContext) {
                throw new JclSerializer.SyntaxErrorException("PEND without an in-stream PROC");
            }
            if (child instanceof JCLParser.ProcStatementContext procStatement) {
                int end = pendAfter(children, at);
                outside.add(new InStreamProc(procStatement, children.subList(at + 1, end)));
                at = end + 1;
                continue;
            }
            outside.add(new Node(child));
            at++;
        }
        return statements(outside);
    }

    private static int pendAfter(List<ParseTree> children, int procAt) {
        for (int i = procAt + 1; i < children.size(); i++) {
            ParseTree child = children.get(i);
            if (child instanceof JCLParser.ProcStatementContext) {
                throw new JclSerializer.SyntaxErrorException("an in-stream PROC inside another");
            }
            if (child instanceof JCLParser.PendStatementContext) {
                return i;
            }
        }
        throw new JclSerializer.SyntaxErrorException("in-stream PROC without PEND");
    }

    /** One entry of a statement list: a parse node, or an in-stream PROC gathered with its body. */
    private sealed interface Piece permits Node, InStreamProc {
    }

    private record Node(ParseTree tree) implements Piece {
    }

    private record InStreamProc(JCLParser.ProcStatementContext statement, List<ParseTree> body) implements Piece {
    }

    private static List<Piece> nodes(List<ParseTree> children) {
        return children.stream().<Piece>map(Node::new).toList();
    }

    private JsonObject proc(Optional<JCLParser.ProcStatementContext> statement, List<ParseTree> body) {
        JsonObject proc = new JsonObject();
        proc.addProperty("kind", "proc");
        proc.addProperty("name", statement.flatMap(s -> Trees.first(s, JCLParser.ProcNameContext.class))
                .map(ParseTree::getText).orElse(""));
        JsonArray defaults = new JsonArray();
        statement.ifPresent(s -> Trees.all(s, JCLParser.DefineSymbolicParameterContext.class)
                .forEach(d -> defaults.add(symbolValue(
                        Trees.token(d, JCLLexer.PROC_PARM_NAME).orElseThrow().getText(),
                        Optional.ofNullable(d.keywordOrSymbolic())))));
        proc.add("defaults", defaults);
        proc.add("statements", statements(nodes(body)));
        return proc;
    }

    private static JsonObject symbolValue(String name, Optional<? extends ParseTree> value) {
        JsonObject symbol = new JsonObject();
        symbol.addProperty("name", name);
        symbol.add("value", value.map(ValueParts::of).orElseGet(JsonArray::new));
        return symbol;
    }

    private JsonArray statements(List<Piece> pieces) {
        JsonArray top = new JsonArray();
        Deque<OpenIf> open = new ArrayDeque<>();
        for (Piece piece : pieces) {
            if (piece instanceof InStreamProc defined) {
                current(open, top).add(procDefinition(defined));
                continue;
            }
            ParseTree child = ((Node) piece).tree();
            switch (child) {
                case JCLParser.JclStepContext step -> current(open, top).add(step(step));
                case JCLParser.SetStatementContext set -> current(open, top).add(set(set));
                case JCLParser.IfStatementContext ifStatement -> open.push(new OpenIf(ifStatement));
                case JCLParser.ElseStatementContext e -> innermost(open, "ELSE").enterElse();
                case JCLParser.EndifStatementContext e -> {
                    JsonObject block = innermost(open, "ENDIF").close();
                    open.pop();
                    current(open, top).add(block);
                }
                default -> {
                }
            }
        }
        if (!open.isEmpty()) {
            throw new JclSerializer.SyntaxErrorException("IF without ENDIF");
        }
        return top;
    }

    private JsonObject procDefinition(InStreamProc defined) {
        JsonObject statement = new JsonObject();
        statement.addProperty("kind", "proc_def");
        statement.add("proc", proc(Optional.of(defined.statement()), defined.body()));
        return statement;
    }

    private static OpenIf innermost(Deque<OpenIf> open, String statement) {
        if (open.isEmpty()) {
            throw new JclSerializer.SyntaxErrorException(statement + " without IF");
        }
        return open.peek();
    }

    private static JsonArray current(Deque<OpenIf> open, JsonArray top) {
        return open.isEmpty() ? top : open.peek().current();
    }

    private static JsonObject set(JCLParser.SetStatementContext ctx) {
        JsonObject set = new JsonObject();
        set.addProperty("kind", "set");
        JsonArray assignments = new JsonArray();
        ctx.setOperation().forEach(o -> assignments.add(symbolValue(
                o.SET_PARM_NAME().getText(), Optional.ofNullable(o.keywordOrSymbolic()))));
        set.add("assignments", assignments);
        return set;
    }

    private JsonObject step(JCLParser.JclStepContext ctx) {
        JCLParser.ExecStatementContext exec = ctx.execStatement();
        if (exec.execPgmStatement() != null) {
            return program(exec.execPgmStatement(), ctx);
        }
        return procCall(exec.execProcStatement(), ctx);
    }

    private static String label(ParseTree statement) {
        return Trees.first(statement, JCLParser.StepNameContext.class).map(ParseTree::getText).orElse("");
    }

    private static String qualifier(TerminalNode parameter) {
        String text = parameter.getText();
        int dot = text.indexOf('.');
        return dot < 0 ? "" : text.substring(dot + 1);
    }

    private static JsonArray parm(JCLParser.ExecParmPARMContext ctx) {
        return Trees.first(ctx, JCLParser.KeywordOrSymbolicContext.class)
                .map(ValueParts::of).orElseGet(JsonArray::new);
    }

    private JsonObject program(JCLParser.ExecPgmStatementContext ctx, JCLParser.JclStepContext step) {
        JsonObject program = new JsonObject();
        program.addProperty("kind", "program");
        program.addProperty("label", label(ctx));
        program.addProperty("pgm", ctx.keywordOrSymbolic().getText());
        program.add("parm", Trees.first(ctx, JCLParser.ExecParmPARMContext.class)
                .map(DocumentBuilder::parm).orElseGet(JsonArray::new));
        program.add("cond", Trees.first(ctx, JCLParser.ExecParmCONDContext.class)
                .map(ConditionReader::read).orElseGet(ConditionReader::none));
        JsonArray dds = new JsonArray();
        step.ddStatementAmalgamation().forEach(dd -> dds.add(DdBuilder.build(dd)));
        program.add("dds", dds);
        return program;
    }

    private JsonObject procCall(JCLParser.ExecProcStatementContext ctx, JCLParser.JclStepContext step) {
        JsonObject call = new JsonObject();
        call.addProperty("kind", "proc_call");
        call.addProperty("label", label(ctx));
        call.addProperty("proc", ctx.keywordOrSymbolic().getText());
        JsonArray symbols = new JsonArray();
        ctx.execProcParm().forEach(p -> symbols.add(symbolValue(
                p.EXEC_PROC_PARM().getText(), Optional.ofNullable(p.keywordOrSymbolic()))));
        call.add("symbol_overrides", symbols);
        JsonArray parms = new JsonArray();
        JsonArray conds = new JsonArray();
        Trees.all(ctx, JCLParser.ExecParmPARMContext.class).forEach(p -> {
            JsonObject override = new JsonObject();
            override.addProperty("procstep", qualifier(p.EXEC_PARM()));
            override.add("parm", parm(p));
            parms.add(override);
        });
        Trees.all(ctx, JCLParser.ExecParmCONDContext.class).forEach(c -> {
            JsonObject override = new JsonObject();
            override.addProperty("procstep", qualifier(c.EXEC_COND()));
            override.add("cond", ConditionReader.read(c));
            conds.add(override);
        });
        call.add("parm_overrides", parms);
        call.add("cond_overrides", conds);
        JsonArray dds = new JsonArray();
        step.ddStatementAmalgamation().forEach(dd -> {
            JsonObject override = new JsonObject();
            override.addProperty("procstep", DdBuilder.procstep(dd));
            override.add("dd", DdBuilder.build(dd));
            dds.add(override);
        });
        call.add("dd_overrides", dds);
        return call;
    }
}
