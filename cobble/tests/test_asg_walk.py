"""The one ASG descent, which must not enumerate nesting keys."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.asg_walk import descend


def test_descend_yields_the_root_first():
    root = {"type": "MOVE"}
    assert list(descend(root))[0] is root


def test_descend_reaches_a_statement_under_an_unenumerated_nesting_key():
    """at_end is not children; a walk that enumerates keys misses it."""
    asg = {
        "type": "READ",
        "at_end": [{"type": "IF", "else_children": [{"type": "MOVE", "operands": []}]}],
    }
    types = [n.get("type") for n in descend(asg) if isinstance(n, dict)]
    assert types == ["READ", "IF", "MOVE"]


def test_descend_finishes_a_subtree_before_starting_the_next_sibling():
    """Depth-first, not breadth-first.

    Every other fixture here is a linear chain, where any traversal order looks
    the same. This one branches: a walk that pushes children onto the front of
    the stack while popping off the back yields DEEP after SECOND.
    """
    asg = {
        "type": "IF",
        "children": [{"type": "EVALUATE", "whens": [{"type": "DEEP"}]}],
        "else_children": [{"type": "SECOND"}],
    }
    types = [n.get("type") for n in descend(asg) if isinstance(n, dict)]
    assert types == ["IF", "EVALUATE", "DEEP", "SECOND"]


def test_descend_does_not_split_strings_into_characters():
    assert "ABC" in list(descend({"name": "ABC"}))
    assert "A" not in list(descend({"name": "ABC"}))


def test_descend_enters_dataclass_fields():
    @dataclass(frozen=True)
    class Leaf:
        name: str

    @dataclass(frozen=True)
    class Branch:
        arms: tuple[Leaf, ...]

    leaf = Leaf(name="WS-A")
    assert leaf in list(descend(Branch(arms=(leaf,))))


def test_descend_survives_nesting_deeper_than_the_recursion_limit():
    """29+ levels are observed in the corpus; the walk must not be recursive."""
    node: dict = {"type": "MOVE"}
    for _ in range(5000):
        node = {"type": "IF", "children": [node]}
    assert sum(1 for _ in descend(node)) > 5000
