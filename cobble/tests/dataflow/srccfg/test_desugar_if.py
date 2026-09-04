"""Short-circuit lowering, which is the whole design.

Two TEST nodes chained on their TRUE edges are AND; chained on their FALSE edges
they are OR; NOT is a swap of a fragment's exits. Everything the spec claims about
reaching conditions -- no normal form, no solver, and a correct ELSE arm -- follows
from these tests passing.
"""

from __future__ import annotations

from cobble.dataflow.depgraph.flows import program_context

from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind, NodeKind
from cobble.dataflow.srccfg.conditions import condition_index, read_condition
from cobble.dataflow.srccfg.desugar import (
    Ctx,
    as_fragment,
    lower_condition,
    lower_statements,
)


def _ctx(asg) -> Ctx:
    return Ctx(
        program=asg.program_id,
        paragraph="MAIN",
        flows=program_context(asg),
        index=condition_index(asg),
    )


def _rel(left: str, right: str) -> dict:
    return {
        "not": False,
        "relation": {
            "left": {"kind": "ref", "name": left},
            "op": "==",
            "right": {"kind": "lit", "value": right},
        },
    }


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _cfg(program_of, statements: list[dict]) -> Cfg:
    asg = program_of(statements)
    fragment = lower_statements(asg.paragraphs[0].statements, _ctx(asg), "")
    return Cfg(program="PROGA", nodes=fragment.nodes, edges=fragment.edges)


def _atom_texts(cfg: Cfg) -> list[str]:
    return [n.atom.text for n in cfg.nodes if n.kind == NodeKind.TEST]


def test_one_atom_lowers_to_one_test_with_a_true_and_a_false_exit(program_of) -> None:
    asg = program_of([])
    frag = lower_condition(read_condition(_rel("WS-FLAG-A", "'Y'")), _ctx(asg), "0", "")

    assert frag.nodes[0].kind == NodeKind.TEST
    assert frag.nodes[0].atom.left == "WS-FLAG-A"
    assert [e.kind for e in frag.true_exits] == [EdgeKind.TRUE]
    assert [e.kind for e in frag.false_exits] == [EdgeKind.FALSE]
    assert frag.true_exits[0].node_id == frag.false_exits[0].node_id


def test_an_88_in_a_guard_is_resolved_to_its_parent_field(program_of) -> None:
    """The resolution from Task 3 has to happen during lowering, not in a later
    pass: the TEST node is what every query reads, so the parent field has to be
    on the node."""
    asg = program_of(
        [],
        data_fields=[
            {
                "name": "WS-STATUS",
                "level": 1,
                "pic": "X(1)",
                "conditions": [{"name": "STATUS-ACTIVE", "values": [{"from": "'A'"}]}],
            }
        ],
    )

    frag = lower_condition(read_condition("STATUS-ACTIVE"), _ctx(asg), "0", "")

    assert frag.nodes[0].atom.left == "WS-STATUS"


def test_and_chains_the_two_tests_on_the_true_edge(program_of) -> None:
    """The definition of short-circuit AND: B is only evaluated when A held, so the
    only way into B is A's TRUE edge."""
    asg = program_of([])
    cond = read_condition(
        {
            "op": "AND",
            "left": _rel("WS-FLAG-A", "'Y'"),
            "right": _rel("WS-TYPE-B", "'G'"),
        }
    )

    frag = lower_condition(cond, _ctx(asg), "0", "")

    first, second = frag.nodes
    assert frag.entry == first.id
    assert [(e.source, e.target, e.kind) for e in frag.edges] == [
        (first.id, second.id, EdgeKind.TRUE)
    ]
    assert [e.node_id for e in frag.true_exits] == [second.id]
    assert [e.node_id for e in frag.false_exits] == [first.id, second.id]


def test_or_chains_the_two_tests_on_the_false_edge(program_of) -> None:
    asg = program_of([])
    cond = read_condition(
        {
            "op": "OR",
            "left": _rel("WS-FLAG-A", "'Y'"),
            "right": _rel("WS-TYPE-B", "'G'"),
        }
    )

    frag = lower_condition(cond, _ctx(asg), "0", "")

    first, second = frag.nodes
    assert [(e.source, e.target, e.kind) for e in frag.edges] == [
        (first.id, second.id, EdgeKind.FALSE)
    ]
    assert [e.node_id for e in frag.true_exits] == [first.id, second.id]
    assert [e.node_id for e in frag.false_exits] == [second.id]


def test_not_swaps_the_true_and_false_exits_and_emits_no_extra_node(
    program_of,
) -> None:
    """This is why NOT is not a term. Swapping the edges of the fragment means the
    negation of a chain comes out right for free, and there is nothing to
    normalise."""
    asg = program_of([])
    plain = lower_condition(
        read_condition(_rel("WS-FLAG-A", "'Y'")), _ctx(asg), "0", ""
    )
    negated = lower_condition(
        read_condition({"not": True, "condition": _rel("WS-FLAG-A", "'Y'")}),
        _ctx(asg),
        "0",
        "",
    )

    assert len(negated.nodes) == len(plain.nodes) == 1
    assert negated.true_exits == plain.false_exits
    assert negated.false_exits == plain.true_exits


def test_not_of_an_and_reaches_its_true_side_by_two_paths(program_of) -> None:
    """NOT (A AND B) is NOT A OR NOT B. Nothing computes that here: swapping the
    exits of the AND chain leaves the FALSE edges of both tests as the true side,
    which IS the disjunction, expressed as two paths."""
    asg = program_of([])
    cond = read_condition(
        {
            "not": True,
            "condition": {
                "op": "AND",
                "left": _rel("WS-FLAG-A", "'Y'"),
                "right": _rel("WS-TYPE-B", "'G'"),
            },
        }
    )

    frag = lower_condition(cond, _ctx(asg), "0", "")

    assert len(frag.true_exits) == 2
    assert [e.kind for e in frag.true_exits] == [EdgeKind.FALSE, EdgeKind.FALSE]


def test_each_test_node_gets_its_own_id_within_the_statement(program_of) -> None:
    """Two atoms of one IF are two nodes of one statement, so the ids are the
    statement path plus a slot, and the slot says where in the condition tree the
    atom was."""
    asg = program_of([])
    cond = read_condition(
        {
            "op": "AND",
            "left": _rel("WS-FLAG-A", "'Y'"),
            "right": _rel("WS-TYPE-B", "'G'"),
        }
    )

    frag = lower_condition(cond, _ctx(asg), "0", "")

    assert [node.id for node in frag.nodes] == ["MAIN/0#test.L", "MAIN/0#test.R"]


def test_an_if_wires_the_then_arm_to_the_true_edge(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            {
                "type": "IF",
                "condition": _rel("WS-FLAG-A", "'Y'"),
                "children": [_move("'F'", "WS-RESULT")],
            }
        ],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert [(e.target, e.kind) for e in cfg.successors(test_node.id)] == [
        ("MAIN/0.then.0", EdgeKind.TRUE)
    ]


def test_an_if_with_no_else_leaves_the_false_edge_for_what_follows(program_of) -> None:
    """The statement after END-IF is reached both by falling out of the THEN arm
    and by the guard failing, so both have to be exits of the IF fragment."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "IF",
                "condition": _rel("WS-FLAG-A", "'Y'"),
                "children": [_move("'F'", "WS-RESULT")],
            },
            _move("WS-RESULT", "WS-COPY"),
        ],
    )

    into_last = {e.source for e in cfg.predecessors("MAIN/1")}
    assert into_last == {"MAIN/0.then.0", "MAIN/0#test"}


def test_both_arms_of_an_if_else_continue_into_the_next_statement(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            {
                "type": "IF",
                "condition": _rel("WS-FLAG-A", "'Y'"),
                "children": [_move("'F'", "WS-RESULT")],
                "else_children": [_move("'G'", "WS-RESULT")],
            },
            _move("WS-RESULT", "WS-COPY"),
        ],
    )

    assert {e.source for e in cfg.predecessors("MAIN/1")} == {
        "MAIN/0.then.0",
        "MAIN/0.else.0",
    }


def test_the_else_arm_of_a_two_clause_and_is_reached_by_two_paths(program_of) -> None:
    """The measured failure of the ancestor-walk probe, now a test.

        IF A AND B ... ELSE ... END-IF

    The ELSE arm is NOT A OR NOT B, so it has two predecessors: the FALSE edge of
    A, and the FALSE edge of B. A guard stack that negates the arm as a
    conjunction reports one path and it is the wrong one.
    """
    cfg = _cfg(
        program_of,
        [
            {
                "type": "IF",
                "condition": {
                    "op": "AND",
                    "left": _rel("WS-FLAG-A", "'Y'"),
                    "right": _rel("WS-TYPE-B", "'G'"),
                },
                "children": [_move("'F'", "WS-RESULT")],
                "else_children": [_move("WS-TYPE-B", "WS-RESULT")],
            }
        ],
    )

    into_else = {(e.source, e.kind) for e in cfg.predecessors("MAIN/0.else.0")}
    assert into_else == {
        ("MAIN/0#test.L", EdgeKind.FALSE),
        ("MAIN/0#test.R", EdgeKind.FALSE),
    }


def test_a_nested_if_keeps_every_atom_as_its_own_test(program_of) -> None:
    """The shape a dictionary rule is usually written in: an outer emptiness guard
    around an inner two-clause test. Four atoms, four TEST nodes, and the inner
    arm's assignment is under all of them."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "IF",
                "condition": {
                    "op": "OR",
                    "left": _rel("WS-RESULT", "SPACES"),
                    "right": _rel("WS-RESULT", "LOW-VALUES"),
                },
                "children": [
                    {
                        "type": "IF",
                        "condition": {
                            "op": "AND",
                            "left": _rel("WS-FLAG-A", "'Y'"),
                            "right": _rel("WS-TYPE-B", "'G'"),
                        },
                        "children": [_move("'F'", "WS-RESULT")],
                        "else_children": [_move("WS-TYPE-B", "WS-RESULT")],
                    }
                ],
            }
        ],
    )

    assert len([n for n in cfg.nodes if n.kind == NodeKind.TEST]) == 4
    assert _atom_texts(cfg)[:2] == ["WS-RESULT == SPACES", "WS-RESULT == LOW-VALUES"]
    assert cfg.node("MAIN/0.then.0.then.0").writes == ("WS-RESULT",)


def test_a_condition_with_no_readable_shape_still_gets_a_test(program_of) -> None:
    """An UNRESOLVED guard is a fork that exists, so the two arms stay distinct
    paths. Collapsing it would silently claim the arm is unconditional."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "IF",
                "condition": {"something": "new"},
                "children": [_move("'F'", "WS-RESULT")],
            }
        ],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert test_node.atom.resolved is False
    assert len(cfg.successors(test_node.id)) == 1


def test_as_fragment_places_true_exits_before_false_exits(program_of) -> None:
    """Converting a CondFragment to a Fragment merges the two exit sets with the
    true exits first, which is the only ordering promise it makes."""
    asg = program_of([])
    cond = lower_condition(read_condition(_rel("WS-FLAG-A", "'Y'")), _ctx(asg), "0", "")

    fragment = as_fragment(cond)

    assert [e.kind for e in fragment.exits] == [EdgeKind.TRUE, EdgeKind.FALSE]
