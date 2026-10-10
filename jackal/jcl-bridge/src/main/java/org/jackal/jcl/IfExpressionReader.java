package org.jackal.jcl;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.antlr.v4.runtime.tree.ParseTree;
import org.antlr.v4.runtime.tree.TerminalNode;

import java.util.List;
import java.util.Map;

/** An IF relational expression as a tree: NOT binds tightest, AND and OR are equal and read left to right. */
final class IfExpressionReader {

    private static final Map<Integer, String> OPERATORS = Map.of(
            JCLParser.IF_EQ, "EQ", JCLParser.IF_NE, "NE",
            JCLParser.IF_GT, "GT", JCLParser.IF_GE, "GE",
            JCLParser.IF_LT, "LT", JCLParser.IF_LE, "LE",
            JCLParser.IF_NG, "LE", JCLParser.IF_NL, "GE");

    private final List<ParseTree> items;
    private int next;

    private IfExpressionReader(List<ParseTree> items) {
        this.items = items;
    }

    static JsonObject read(JCLParser.IfStatementContext ctx) {
        List<ParseTree> children = Trees.children(ctx);
        int start = indexOf(children, JCLParser.IF) + 1;
        int end = indexOf(children, JCLParser.THEN);
        IfExpressionReader reader = new IfExpressionReader(children.subList(start, end));
        JsonObject expression = reader.expression();
        if (reader.next != reader.items.size()) {
            throw new JclSerializer.SyntaxErrorException("unbalanced IF expression: " + ctx.getText());
        }
        return expression;
    }

    private static int indexOf(List<ParseTree> children, int type) {
        for (int i = 0; i < children.size(); i++) {
            if (Trees.isToken(children.get(i), type)) {
                return i;
            }
        }
        throw new JclSerializer.SyntaxErrorException("IF statement without token " + type);
    }

    private boolean at(int type) {
        return next < items.size() && Trees.isToken(items.get(next), type);
    }

    private JsonObject expression() {
        JsonObject result = unary();
        String chain = "";
        JsonArray operands = new JsonArray();
        operands.add(result);
        while (at(JCLParser.IF_LOGICAL)) {
            String operator = logical(items.get(next++).getText());
            JsonObject operand = unary();
            if (!chain.isEmpty() && !chain.equals(operator)) {
                JsonObject collapsed = node(chain, operands);
                operands = new JsonArray();
                operands.add(collapsed);
            }
            chain = operator;
            operands.add(operand);
        }
        return chain.isEmpty() ? result : node(chain, operands);
    }

    private static String logical(String text) {
        return switch (text.toUpperCase()) {
            case "AND", "&" -> "and";
            case "OR", "|" -> "or";
            default -> throw new JclSerializer.SyntaxErrorException("not a logical operator: " + text);
        };
    }

    private static JsonObject node(String kind, JsonArray operands) {
        JsonObject node = new JsonObject();
        node.addProperty("kind", kind);
        node.add("operands", operands);
        return node;
    }

    private JsonObject unary() {
        if (at(JCLParser.NOT_SYMBOL)) {
            next++;
            return negated(unary());
        }
        if (at(JCLParser.LPAREN)) {
            next++;
            JsonObject inner = expression();
            if (!at(JCLParser.RPAREN)) {
                throw new JclSerializer.SyntaxErrorException("IF expression missing a closing parenthesis");
            }
            next++;
            return inner;
        }
        if (next < items.size() && items.get(next) instanceof JCLParser.IfTestContext test) {
            next++;
            return term(test);
        }
        throw new JclSerializer.SyntaxErrorException("IF expression expected a term");
    }

    private static JsonObject negated(JsonObject operand) {
        JsonObject not = new JsonObject();
        not.addProperty("kind", "not");
        not.add("operand", operand);
        return not;
    }

    private static JsonObject term(JCLParser.IfTestContext test) {
        JsonObject target = Trees.token(test, JCLParser.IF_STEP)
                .map(step -> Targets.named(step.getText().substring(0, step.getText().length() - 1)))
                .orElseGet(Targets::allPrior);
        TerminalNode subject = (TerminalNode) test.ifKeyword().getChild(0);
        int subjectType = subject.getSymbol().getType();
        int operator = test.ifRelOp() == null
                ? JCLParser.IF_EQ
                : ((TerminalNode) test.ifRelOp().getChild(0)).getSymbol().getType();
        String value = test.ifRelOp() == null ? "TRUE" : test.getChild(test.getChildCount() - 1).getText();
        if (subjectType == JCLParser.RC) {
            return rc(target, operator, value);
        }
        if (subjectType == JCLParser.ABENDCC) {
            return truth(abendCode(target, value), operator, "TRUE");
        }
        return truth(state(subjectType == JCLParser.ABEND ? "abend" : "run", target), operator, value);
    }

    private static JsonObject rc(JsonObject target, int operator, String value) {
        JsonObject rc = new JsonObject();
        rc.addProperty("kind", "rc");
        rc.add("target", target);
        rc.addProperty("op", OPERATORS.get(operator));
        rc.addProperty("code", Integer.parseInt(value));
        return rc;
    }

    private static JsonObject state(String kind, JsonObject target) {
        JsonObject state = new JsonObject();
        state.addProperty("kind", kind);
        state.add("target", target);
        return state;
    }

    private static JsonObject abendCode(JsonObject target, String value) {
        JsonObject abend = new JsonObject();
        String upper = value.toUpperCase();
        if (upper.startsWith("S")) {
            abend.addProperty("kind", "system");
            abend.addProperty("code", Integer.parseInt(upper.substring(1), 16));
        } else if (upper.startsWith("U")) {
            abend.addProperty("kind", "user");
            abend.addProperty("code", Integer.parseInt(upper.substring(1)));
        } else {
            throw new JclSerializer.SyntaxErrorException("ABENDCC value is neither Sxxx nor Uxxxx: " + value);
        }
        JsonObject test = state("abend_code", target);
        test.add("abend", abend);
        return test;
    }

    private static JsonObject truth(JsonObject test, int operator, String value) {
        boolean wantsTrue = value.equalsIgnoreCase("TRUE");
        if (!wantsTrue && !value.equalsIgnoreCase("FALSE")) {
            throw new JclSerializer.SyntaxErrorException("expected TRUE or FALSE, found " + value);
        }
        boolean equal = switch (operator) {
            case JCLParser.IF_EQ -> true;
            case JCLParser.IF_NE -> false;
            default -> throw new JclSerializer.SyntaxErrorException("ABEND, ABENDCC and RUN take = or NE only");
        };
        return equal == wantsTrue ? test : negated(test);
    }
}
