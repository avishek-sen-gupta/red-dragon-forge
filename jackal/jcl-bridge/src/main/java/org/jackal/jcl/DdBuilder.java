package org.jackal.jcl;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.antlr.v4.runtime.tree.ParseTree;
import org.antlr.v4.runtime.tree.TerminalNode;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/** A DD statement, with the unnamed DDs after it as its concatenated members. */
final class DdBuilder {

    private record Fields(
            Optional<JCLParser.DatasetNameContext> dsn,
            JsonArray disp,
            boolean sysout,
            boolean dummy,
            boolean inStream) {

        static Fields empty() {
            return new Fields(Optional.empty(), new JsonArray(), false, false, false);
        }
    }

    private DdBuilder() {
    }

    static String ddname(JCLParser.DdStatementAmalgamationContext ctx) {
        String[] names = ddNameParts(ctx);
        return names[names.length - 1];
    }

    static String procstep(JCLParser.DdStatementAmalgamationContext ctx) {
        String[] names = ddNameParts(ctx);
        return names.length == 1 ? "" : names[0];
    }

    private static String[] ddNameParts(JCLParser.DdStatementAmalgamationContext ctx) {
        return ctx.ddStatement().ddName().getText().split("\\.");
    }

    static JsonObject build(JCLParser.DdStatementAmalgamationContext ctx) {
        JCLParser.DdStatementContext statement = ctx.ddStatement();
        JsonObject dd = new JsonObject();
        dd.addProperty("ddname", ddname(ctx));
        Fields fields = fields(statement);
        dd.add("dsn", dsn(fields));
        dd.add("disp", fields.disp());
        dd.add("in_stream", cards(statement));
        dd.addProperty("sysout", fields.sysout());
        JsonArray members = new JsonArray();
        ctx.ddStatementConcatenation().forEach(member -> members.add(member(member)));
        dd.add("concatenated", members);
        return dd;
    }

    private static JsonObject member(JCLParser.DdStatementConcatenationContext ctx) {
        Fields fields = fields(ctx);
        JsonObject member = new JsonObject();
        member.add("dsn", dsn(fields));
        member.add("disp", fields.disp());
        member.add("in_stream", cards(ctx));
        return member;
    }

    private static Fields fields(ParseTree statement) {
        return Trees.children(statement, JCLParser.DdParameterContext.class).stream()
                .map(param -> param.getChild(0))
                .reduce(Fields.empty(), DdBuilder::fold, (a, b) -> b);
    }

    private static Fields fold(Fields acc, ParseTree inner) {
        return switch (inner) {
            case JCLParser.DdParmDSNAMEContext c -> new Fields(
                    Trees.first(c, JCLParser.DatasetNameContext.class), acc.disp(), acc.sysout(),
                    acc.dummy(), acc.inStream());
            case JCLParser.DdParmDISPContext c -> new Fields(
                    acc.dsn(),
                    Trees.first(c, JCLParser.SingleOrMultipleValueContext.class)
                            .map(DdBuilder::dispWords).orElseGet(JsonArray::new),
                    acc.sysout(), acc.dummy(), acc.inStream());
            case JCLParser.DdParmSYSOUTContext c -> new Fields(acc.dsn(), acc.disp(), true, acc.dummy(), acc.inStream());
            case JCLParser.DdParmDUMMYContext c -> new Fields(acc.dsn(), acc.disp(), acc.sysout(), true, acc.inStream());
            case JCLParser.DdParmASTERISKContext c -> new Fields(acc.dsn(), acc.disp(), acc.sysout(), acc.dummy(), true);
            case JCLParser.DdParmDATAContext c -> new Fields(acc.dsn(), acc.disp(), acc.sysout(), acc.dummy(), true);
            default -> acc;
        };
    }

    private static JsonObject dsn(Fields fields) {
        if (fields.dummy()) {
            return kind("dummy");
        }
        if (fields.dsn().isPresent()) {
            return named(fields.dsn().get());
        }
        return kind(fields.inStream() ? "in_stream" : "none");
    }

    private static JsonObject named(JCLParser.DatasetNameContext datasetName) {
        String raw = datasetName.getText();
        if (raw.startsWith("*.")) {
            int last = raw.lastIndexOf('.');
            JsonObject backref = kind("backref");
            backref.add("target", Targets.named(raw.substring(2, last)));
            backref.addProperty("ddname", raw.substring(last + 1));
            return backref;
        }
        if (raw.startsWith("&&")) {
            JsonObject temp = kind("temp");
            temp.addProperty("name", raw.substring(2));
            return temp;
        }
        if (raw.equals("NULLFILE")) {
            return kind("dummy");
        }
        JsonObject name = kind("name");
        name.add("value", ValueParts.of(datasetName));
        return name;
    }

    private static JsonObject kind(String kind) {
        JsonObject dsn = new JsonObject();
        dsn.addProperty("kind", kind);
        return dsn;
    }

    private static JsonArray cards(ParseTree statement) {
        StringBuilder raw = new StringBuilder();
        Trees.children(statement, JCLParser.DdParmASTERISK_DATAContext.class).forEach(data ->
                Trees.children(data).stream()
                        .filter(t -> Trees.isToken(t, JCLLexer.DD_ASTERISK_DATA))
                        .forEach(t -> raw.append(t.getText())));
        JsonArray lines = new JsonArray();
        if (raw.isEmpty()) {
            return lines;
        }
        String text = raw.toString().replace("\r\n", "\n");
        String body = text.endsWith("\n") ? text.substring(0, text.length() - 1) : text;
        for (String line : body.split("\n", -1)) {
            lines.add(line);
        }
        return lines;
    }

    private static JsonArray dispWords(JCLParser.SingleOrMultipleValueContext ctx) {
        List<String> slots = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        for (TerminalNode t : Trees.terminals(ctx)) {
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
        JsonArray words = new JsonArray();
        if (slots.size() == 1 && slots.get(0).isEmpty()) {
            return words;
        }
        slots.forEach(words::add);
        return words;
    }
}
