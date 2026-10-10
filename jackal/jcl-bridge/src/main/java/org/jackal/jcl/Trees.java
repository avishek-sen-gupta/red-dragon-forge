package org.jackal.jcl;

import org.antlr.v4.runtime.tree.ParseTree;
import org.antlr.v4.runtime.tree.TerminalNode;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.stream.IntStream;

/** Lookups over an ANTLR parse tree. */
final class Trees {

    private Trees() {
    }

    static <T extends ParseTree> Optional<T> first(ParseTree node, Class<T> type) {
        for (int i = 0; i < node.getChildCount(); i++) {
            ParseTree child = node.getChild(i);
            if (type.isInstance(child)) {
                return Optional.of(type.cast(child));
            }
            Optional<T> found = first(child, type);
            if (found.isPresent()) {
                return found;
            }
        }
        return Optional.empty();
    }

    static <T extends ParseTree> List<T> all(ParseTree node, Class<T> type) {
        List<T> out = new ArrayList<>();
        collect(node, type, out);
        return out;
    }

    private static <T extends ParseTree> void collect(ParseTree node, Class<T> type, List<T> out) {
        for (int i = 0; i < node.getChildCount(); i++) {
            ParseTree child = node.getChild(i);
            if (type.isInstance(child)) {
                out.add(type.cast(child));
            }
            collect(child, type, out);
        }
    }

    static List<ParseTree> children(ParseTree node) {
        return IntStream.range(0, node.getChildCount()).mapToObj(node::getChild).toList();
    }

    static <T extends ParseTree> List<T> children(ParseTree node, Class<T> type) {
        return children(node).stream().filter(type::isInstance).map(type::cast).toList();
    }

    static List<TerminalNode> terminals(ParseTree node) {
        List<TerminalNode> out = new ArrayList<>();
        addTerminals(node, out);
        return out;
    }

    private static void addTerminals(ParseTree node, List<TerminalNode> out) {
        if (node instanceof TerminalNode t) {
            out.add(t);
            return;
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            addTerminals(node.getChild(i), out);
        }
    }

    static boolean isToken(ParseTree node, int type) {
        return node instanceof TerminalNode t && t.getSymbol().getType() == type;
    }

    static Optional<TerminalNode> token(ParseTree node, int type) {
        return children(node).stream()
                .filter(c -> isToken(c, type))
                .map(TerminalNode.class::cast)
                .findFirst();
    }
}
