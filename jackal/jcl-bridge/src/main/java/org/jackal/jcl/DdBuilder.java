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

    /**
     * The record attributes jackal models: DCB's model (positional), RECFM and LRECL, whether DCB= was
     * coded, and the LIKE and REFDD sources.
     */
    private record Dcb(
            Optional<JCLParser.DatasetNameContext> source,
            Optional<JCLParser.KeywordOrSymbolicContext> recfm,
            Optional<JCLParser.KeywordOrSymbolicContext> lrecl,
            boolean coded,
            Optional<JCLParser.DatasetNameContext> like,
            Optional<JCLParser.DatasetNameContext> refdd) {

        static Dcb empty() {
            return new Dcb(Optional.empty(), Optional.empty(), Optional.empty(), false, Optional.empty(),
                    Optional.empty());
        }

        Dcb withSource(JCLParser.DatasetNameContext name) {
            return new Dcb(Optional.of(name), recfm, lrecl, coded, like, refdd);
        }

        Dcb withRecfm(JCLParser.KeywordOrSymbolicContext value) {
            return new Dcb(source, Optional.ofNullable(value), lrecl, coded, like, refdd);
        }

        Dcb withLrecl(JCLParser.KeywordOrSymbolicContext value) {
            return new Dcb(source, recfm, Optional.ofNullable(value), coded, like, refdd);
        }

        Dcb asCoded() {
            return new Dcb(source, recfm, lrecl, true, like, refdd);
        }

        Dcb withLike(JCLParser.DatasetNameContext name) {
            return new Dcb(source, recfm, lrecl, coded, Optional.ofNullable(name), refdd);
        }

        Dcb withRefdd(JCLParser.DatasetNameContext name) {
            return new Dcb(source, recfm, lrecl, coded, like, Optional.ofNullable(name));
        }
    }

    private record Fields(
            Optional<JCLParser.DatasetNameContext> dsn,
            JsonArray disp,
            boolean sysout,
            boolean dummy,
            boolean inStream,
            List<String> nullified,
            Dcb dcb,
            Optional<JCLParser.KeywordOrSymbolicContext> gdgOrder) {

        static Fields empty() {
            return new Fields(
                    Optional.empty(), new JsonArray(), false, false, false, List.of(), Dcb.empty(), Optional.empty());
        }

        Fields withNullified(boolean empty, String keyword) {
            if (!empty) {
                return this;
            }
            List<String> more = new ArrayList<>(nullified);
            more.add(keyword);
            return new Fields(dsn, disp, sysout, dummy, inStream, List.copyOf(more), dcb, gdgOrder);
        }

        Fields withDcb(Dcb changed) {
            return new Fields(dsn, disp, sysout, dummy, inStream, nullified, changed, gdgOrder);
        }

        Fields withGdgOrder(JCLParser.KeywordOrSymbolicContext value) {
            return new Fields(dsn, disp, sysout, dummy, inStream, nullified, dcb, Optional.ofNullable(value));
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
        dd.add("nullified", nullified(fields));
        dd.add("in_stream", cards(statement));
        dd.addProperty("sysout", fields.sysout());
        JsonArray members = new JsonArray();
        ctx.ddStatementConcatenation().forEach(member -> members.add(member(member)));
        dd.add("concatenated", members);
        dd.add("dcb", dcb(fields.dcb()));
        dd.add("gdg_order", fields.gdgOrder().map(ValueParts::of).orElseGet(JsonArray::new));
        return dd;
    }

    private static JsonObject member(JCLParser.DdStatementConcatenationContext ctx) {
        Fields fields = fields(ctx);
        JsonObject member = new JsonObject();
        member.add("dsn", dsn(fields));
        member.add("disp", fields.disp());
        member.add("nullified", nullified(fields));
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
                    acc.dummy(), acc.inStream(), acc.nullified(), acc.dcb(), acc.gdgOrder())
                    .withNullified(c.datasetName() == null, "dsn");
            case JCLParser.DdParmDISPContext c -> new Fields(
                    acc.dsn(),
                    Trees.first(c, JCLParser.SingleOrMultipleValueContext.class)
                            .map(DdBuilder::dispWords).orElseGet(JsonArray::new),
                    acc.sysout(), acc.dummy(), acc.inStream(), acc.nullified(), acc.dcb(), acc.gdgOrder())
                    .withNullified(c.singleOrMultipleValue() == null, "disp");
            case JCLParser.DdParmSYSOUTContext c -> new Fields(
                    acc.dsn(), acc.disp(), true, acc.dummy(), acc.inStream(), acc.nullified(), acc.dcb(), acc.gdgOrder());
            case JCLParser.DdParmDUMMYContext c -> new Fields(
                    acc.dsn(), acc.disp(), acc.sysout(), true, acc.inStream(), acc.nullified(), acc.dcb(), acc.gdgOrder());
            case JCLParser.DdParmASTERISKContext c -> new Fields(
                    acc.dsn(), acc.disp(), acc.sysout(), acc.dummy(), true, acc.nullified(), acc.dcb(), acc.gdgOrder());
            case JCLParser.DdParmDATAContext c -> new Fields(
                    acc.dsn(), acc.disp(), acc.sysout(), acc.dummy(), true, acc.nullified(), acc.dcb(), acc.gdgOrder());
            case JCLParser.DdParmDCBContext c -> c.ddParmDCB_Parameter().stream()
                    .reduce(acc.withDcb(acc.dcb().asCoded()),
                            (f, p) -> dcbParameter(f, p.getChild(0), true), (a, b) -> b)
                    .withNullified(c.ddParmDCB_Parameter().isEmpty(), "dcb");
            case JCLParser.DdParmDCB_ParameterContext c -> dcbParameter(acc, c.getChild(0), false);
            case JCLParser.DdParmLIKEContext c -> acc.withDcb(acc.dcb().withLike(c.datasetName()))
                    .withNullified(c.datasetName() == null, "like");
            case JCLParser.DdParmREFDDContext c -> acc.withDcb(acc.dcb().withRefdd(c.datasetName()))
                    .withNullified(c.datasetName() == null, "refdd");
            case JCLParser.DdParmGDGORDERContext c -> acc.withGdgOrder(c.keywordOrSymbolic())
                    .withNullified(c.keywordOrSymbolic() == null, "gdgorder");
            default -> acc;
        };
    }

    private static Fields dcbParameter(Fields acc, ParseTree inner, boolean inDcb) {
        return switch (inner) {
            case JCLParser.DdParmRECFMContext c -> acc.withDcb(acc.dcb().withRecfm(c.keywordOrSymbolic()))
                    .withNullified(c.keywordOrSymbolic() == null, "recfm");
            case JCLParser.DdParmLRECLContext c -> acc.withDcb(acc.dcb().withLrecl(c.keywordOrSymbolic()))
                    .withNullified(c.keywordOrSymbolic() == null, "lrecl");
            case JCLParser.DatasetNameContext c when inDcb -> acc.withDcb(acc.dcb().withSource(c));
            default -> acc;
        };
    }

    private static JsonObject dcb(Dcb dcb) {
        JsonObject out = new JsonObject();
        out.addProperty("coded", dcb.coded());
        out.add("source", dcb.source().map(DdBuilder::named).orElseGet(() -> kind("none")));
        out.add("recfm", dcb.recfm().map(ValueParts::of).orElseGet(JsonArray::new));
        out.add("lrecl", dcb.lrecl().map(ValueParts::of).orElseGet(JsonArray::new));
        out.add("like", dcb.like().map(DdBuilder::named).orElseGet(() -> kind("none")));
        out.add("refdd", dcb.refdd().map(DdBuilder::named).orElseGet(() -> kind("none")));
        return out;
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

    private static JsonArray nullified(Fields fields) {
        JsonArray names = new JsonArray();
        fields.nullified().forEach(names::add);
        return names;
    }

    private static JsonObject named(JCLParser.DatasetNameContext datasetName) {
        String raw = datasetName.getText();
        if (raw.startsWith("*.") && raw.indexOf('.', 2) < 0) {
            JsonObject sameStep = kind("step_dd");
            sameStep.addProperty("ddname", raw.substring(2));
            return sameStep;
        }
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
        List<JCLParser.KeywordOrSymbolicContext> parts = datasetName.keywordOrSymbolic();
        if (parts.size() == 2 && isRelativeGeneration(parts.get(1).getText())) {
            JsonObject generation = kind("generation");
            generation.add("base", ValueParts.of(parts.get(0)));
            generation.addProperty("relative", Integer.parseInt(parts.get(1).getText()));
            return generation;
        }
        JsonObject name = kind("name");
        name.add("value", ValueParts.of(datasetName));
        return name;
    }

    private static boolean isRelativeGeneration(String text) {
        return text.matches("[+-][0-9]{1,3}|0[0-9]{0,2}")
                && Math.abs(Integer.parseInt(text)) <= 255;
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
