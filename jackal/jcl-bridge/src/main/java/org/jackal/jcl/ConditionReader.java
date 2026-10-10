package org.jackal.jcl;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.antlr.v4.runtime.tree.ParseTree;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/** EXEC COND as return-code tests plus EVEN/ONLY, and JOB COND as end-job tests. */
final class ConditionReader {

    private static final Set<String> MODES = Set.of("EVEN", "ONLY");

    private static final Set<String> OPERATORS = Set.of("GT", "GE", "EQ", "NE", "LT", "LE");

    private sealed interface Item permits Open, Close, Word {
    }

    private record Open() implements Item {
    }

    private record Close() implements Item {
    }

    private record Word(String text) implements Item {
    }

    private ConditionReader() {
    }

    static JsonObject none() {
        return condition(new JsonArray(), "NORMAL");
    }

    static JsonObject read(JCLParser.ExecParmCONDContext ctx) {
        List<Item> items = items(ctx);
        if (items.isEmpty()) {
            return none();
        }
        if (!(items.get(0) instanceof Open)) {
            return elements(List.of(items));
        }
        List<Item> inner = items.subList(1, items.size() - 1);
        if (inner.stream().noneMatch(Open.class::isInstance)) {
            return elements(List.of(inner));
        }
        return elements(splitAtTopLevel(inner));
    }

    static JsonArray endJobTests(JCLParser.JobParmCONDContext ctx) {
        JsonArray tests = new JsonArray();
        Trees.all(ctx, JCLParser.ParenListContext.class).stream()
                .map(list -> Trees.all(list, JCLParser.KeywordOrSymbolicContext.class))
                .forEach(words -> {
                    JsonObject test = new JsonObject();
                    test.addProperty("code", Integer.parseInt(words.get(0).getText().trim()));
                    test.addProperty("op", words.get(1).getText().trim().toUpperCase());
                    tests.add(test);
                });
        return tests;
    }

    private static List<Item> items(JCLParser.ExecParmCONDContext ctx) {
        List<Item> items = new ArrayList<>();
        for (ParseTree child : Trees.children(ctx)) {
            if (Trees.isToken(child, JCLParser.LPAREN)) {
                items.add(new Open());
            } else if (Trees.isToken(child, JCLParser.RPAREN)) {
                items.add(new Close());
            } else if (child instanceof JCLParser.KeywordOrSymbolicContext) {
                items.add(new Word(child.getText().trim().toUpperCase()));
            }
        }
        return items;
    }

    private static List<List<Item>> splitAtTopLevel(List<Item> inner) {
        List<List<Item>> elements = new ArrayList<>();
        List<Item> current = new ArrayList<>();
        int depth = 0;
        for (Item item : inner) {
            if (item instanceof Open) {
                depth++;
            } else if (item instanceof Close) {
                depth--;
            } else if (depth == 0) {
                elements.add(List.of(item));
                continue;
            }
            current.add(item);
            if (depth == 0) {
                elements.add(current);
                current = new ArrayList<>();
            }
        }
        return elements;
    }

    private static JsonObject elements(List<List<Item>> elements) {
        JsonArray tests = new JsonArray();
        String mode = "NORMAL";
        for (List<Item> element : elements) {
            List<String> words = element.stream()
                    .filter(Word.class::isInstance)
                    .map(w -> ((Word) w).text())
                    .toList();
            if (words.size() == 1 && MODES.contains(words.get(0))) {
                if (!mode.equals("NORMAL")) {
                    throw new JclSerializer.SyntaxErrorException(
                            "COND names more than one of EVEN and ONLY");
                }
                mode = words.get(0);
            } else {
                tests.add(test(words));
            }
        }
        return condition(tests, mode);
    }

    private static JsonObject test(List<String> words) {
        if (words.size() < 2 || words.size() > 3) {
            throw new JclSerializer.SyntaxErrorException("COND test is not (code,operator[,step]): " + words);
        }
        if (!words.get(0).matches("[0-9]+")) {
            throw new JclSerializer.SyntaxErrorException("COND return code is not a number: " + words.get(0));
        }
        if (!OPERATORS.contains(words.get(1))) {
            throw new JclSerializer.SyntaxErrorException(
                    "COND operator is not GT, GE, EQ, NE, LT or LE: " + words.get(1));
        }
        JsonObject test = new JsonObject();
        test.addProperty("code", Integer.parseInt(words.get(0)));
        test.addProperty("op", words.get(1));
        test.add("target", words.size() == 3 ? Targets.named(words.get(2)) : Targets.allPrior());
        return test;
    }

    private static JsonObject condition(JsonArray tests, String mode) {
        JsonObject cond = new JsonObject();
        cond.add("tests", tests);
        cond.addProperty("mode", mode);
        return cond;
    }
}
