package org.jackal.jcl;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.antlr.v4.runtime.tree.ParseTree;
import org.antlr.v4.runtime.tree.TerminalNode;

/** A JCL value as literal and symbol parts, classified by the lexer's own token types. */
final class ValueParts {

    private final JsonArray parts = new JsonArray();
    private final StringBuilder literalRun = new StringBuilder();
    private boolean afterSymbol;

    private ValueParts() {
    }

    static JsonArray of(ParseTree node) {
        ValueParts value = new ValueParts();
        Trees.terminals(node).forEach(value::add);
        value.flush();
        return value.parts;
    }

    static JsonObject literal(String text) {
        JsonObject part = new JsonObject();
        part.addProperty("kind", "literal");
        part.addProperty("text", text);
        return part;
    }

    private void add(TerminalNode terminal) {
        String text = terminal.getText();
        if (terminal.getSymbol().getType() == JCLLexer.SYMBOLIC) {
            flush();
            JsonObject part = new JsonObject();
            part.addProperty("kind", "symbol");
            part.addProperty("name", text.substring(1));
            parts.add(part);
            afterSymbol = true;
            return;
        }
        literalRun.append(afterSymbol && text.startsWith(".") ? text.substring(1) : text);
        afterSymbol = false;
    }

    private void flush() {
        if (literalRun.length() > 0) {
            parts.add(literal(literalRun.toString()));
            literalRun.setLength(0);
        }
    }
}
