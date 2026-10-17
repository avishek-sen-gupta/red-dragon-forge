"""PERFORM: ranges, the return edge, and the loop forms.

The return edge is where this design over-approximates on purpose. A paragraph
performed from two places has two return edges, so an unconstrained walk can leave
by the wrong one; matching perform edges to return edges along a path is what
prunes that, and it belongs to the reaching-conditions pass, not here.
"""

from __future__ import annotations

from cobble.dataflow.depgraph.flows import program_context

from cobble.dataflow.srccfg.build import (
    build_program,
    end_id,
    label_id,
    paragraph_order,
    paragraph_range,
)
from cobble.dataflow.srccfg.cfg import Edge, EdgeKind, NodeKind
from cobble.dataflow.srccfg.conditions import condition_index
from cobble.dataflow.srccfg.desugar import (
    PERFORM_TRANSFER,
    RANGE_SEPARATOR,
    Ctx,
    lower_statements,
)


def _ctx(asg) -> Ctx:
    return Ctx(
        program=asg.program_id,
        paragraph="MAIN",
        flows=program_context(asg),
        index=condition_index(asg),
    )


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _cond(left: str, right: str) -> dict:
    return {
        "not": False,
        "relation": {
            "left": {"kind": "ref", "name": left},
            "op": "==",
            "right": {"kind": "lit", "value": right},
        },
    }


def _lower(program_of, statements: list[dict]):
    asg = program_of(statements)
    return lower_statements(asg.paragraphs[0].statements, _ctx(asg), "")


def _program(*paragraphs: dict) -> dict:
    return {"program_id": "PROGA", "paragraphs": list(paragraphs)}


def test_a_perform_of_one_paragraph_names_it_as_the_target(program_of) -> None:
    fragment = _lower(program_of, [{"type": "PERFORM", "operands": ["1000-FIRST"]}])

    node = fragment.nodes[0]
    assert (node.kind, node.transfer, node.target) == (
        NodeKind.CALL,
        PERFORM_TRANSFER,
        "1000-FIRST",
    )


def test_a_perform_keeps_a_flow_exit_because_control_comes_back(program_of) -> None:
    """The difference from GO TO, and the only structural difference: a PERFORM
    returns, so the statement after it is reachable."""
    fragment = _lower(program_of, [{"type": "PERFORM", "operands": ["1000-FIRST"]}])

    assert [e.kind for e in fragment.exits] == [EdgeKind.FLOW]


def test_a_perform_thru_stores_both_ends_of_the_range(program_of) -> None:
    fragment = _lower(
        program_of,
        [{"type": "PERFORM", "operands": ["1000-FIRST"], "thru": "3000-THIRD"}],
    )

    assert fragment.nodes[0].target == f"1000-FIRST{RANGE_SEPARATOR}3000-THIRD"


def test_a_range_is_the_paragraphs_between_the_two_ends_in_declaration_order(
    asg_of,
) -> None:
    """PERFORM A THRU C runs everything declared between them, whatever the names
    look like -- the numbering convention is not the order."""
    order = paragraph_order(
        asg_of(
            _program(
                {"name": "1000-FIRST", "statements": []},
                {"name": "2000-SECOND", "statements": []},
                {"name": "3000-THIRD", "statements": []},
            )
        )
    )

    assert paragraph_range(order, "1000-FIRST", "3000-THIRD") == (
        "1000-FIRST",
        "2000-SECOND",
        "3000-THIRD",
    )


def test_a_range_whose_ends_are_the_wrong_way_round_is_just_the_first(asg_of) -> None:
    """A THRU whose second name is declared before its first is a source defect the
    compiler accepts; over-approximating to the whole program would swamp every
    query, so the range is the entry alone."""
    order = paragraph_order(
        asg_of(
            _program(
                {"name": "1000-FIRST", "statements": []},
                {"name": "2000-SECOND", "statements": []},
            )
        )
    )

    assert paragraph_range(order, "2000-SECOND", "1000-FIRST") == ("2000-SECOND",)


def test_a_perform_edge_goes_to_the_label_and_the_return_comes_from_the_range_end(
    asg_of,
) -> None:
    """The range always runs, so the PERFORM's only way on is into it; where it
    continues once the range returns is recorded on the node, not as an edge a
    walk could take instead."""
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "0000-MAIN",
                    "statements": [
                        {
                            "type": "PERFORM",
                            "operands": ["1000-FIRST"],
                            "thru": "2000-SECOND",
                        },
                        _move("'F'", "WS-RESULT"),
                    ],
                },
                {"name": "1000-FIRST", "statements": [_move("'A'", "WS-A")]},
                {"name": "2000-SECOND", "statements": [_move("'B'", "WS-B")]},
            )
        )
    )

    assert [(e.target, e.kind) for e in cfg.successors("0000-MAIN/0")] == [
        (label_id("1000-FIRST"), EdgeKind.PERFORM),
    ]
    assert cfg.node("0000-MAIN/0").resume == "0000-MAIN/1"
    edge_kinds = [
        e.kind
        for e in cfg.successors(end_id("2000-SECOND"))
        if e.target == "0000-MAIN/1"
    ]
    assert edge_kinds == [EdgeKind.RETURN]


def test_a_perform_of_an_undeclared_paragraph_gets_no_edges(asg_of) -> None:
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "0000-MAIN",
                    "statements": [{"type": "PERFORM", "operands": ["NOWHERE"]}],
                }
            )
        )
    )

    assert [e.kind for e in cfg.successors("0000-MAIN/0")] == [EdgeKind.FLOW]
    assert (cfg.node("0000-MAIN/0").target, cfg.node("0000-MAIN/0").resume) == (
        "NOWHERE",
        "",
    )


def test_an_inline_perform_lowers_its_body_in_place(program_of) -> None:
    """PERFORM with a body and no target is a block, not a call: there is no
    paragraph to share, so there is nothing to point at."""
    fragment = _lower(
        program_of,
        [{"type": "PERFORM", "children": [_move("'F'", "WS-RESULT")]}],
    )

    assert [node.id for node in fragment.nodes] == ["MAIN/0.body.0"]
    assert fragment.nodes[0].kind == NodeKind.ASSIGN


def test_perform_until_tests_before_the_body_by_default(program_of) -> None:
    """TEST BEFORE is the default, so a body that never runs is a real path -- and
    an assignment inside the body is guarded by the loop condition being false."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "PERFORM",
                "perform_type": "UNTIL",
                "until": _cond("WS-EOF", "'Y'"),
                "children": [_move("'F'", "WS-RESULT")],
            }
        ],
    )

    test_node = next(n for n in fragment.nodes if n.kind == NodeKind.TEST)
    assert fragment.entry == test_node.id
    assert (
        Edge(source=test_node.id, target="MAIN/0.body.0", kind=EdgeKind.FALSE)
        in fragment.edges
    )
    assert [e.node_id for e in fragment.exits] == [test_node.id]
    assert [e.kind for e in fragment.exits] == [EdgeKind.TRUE]


def test_the_body_of_an_until_loop_goes_back_to_the_test(program_of) -> None:
    fragment = _lower(
        program_of,
        [
            {
                "type": "PERFORM",
                "perform_type": "UNTIL",
                "until": _cond("WS-EOF", "'Y'"),
                "children": [_move("'F'", "WS-RESULT")],
            }
        ],
    )

    test_node = next(n for n in fragment.nodes if n.kind == NodeKind.TEST)
    assert (
        Edge(source="MAIN/0.body.0", target=test_node.id, kind=EdgeKind.FLOW)
        in fragment.edges
    )


def test_perform_until_with_test_after_runs_the_body_first(program_of) -> None:
    """TEST AFTER makes the body unconditional on the first pass, which changes
    what guards an assignment inside it."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "PERFORM",
                "perform_type": "UNTIL",
                "until": _cond("WS-EOF", "'Y'"),
                "test_before": False,
                "children": [_move("'F'", "WS-RESULT")],
            }
        ],
    )

    test_node = next(n for n in fragment.nodes if n.kind == NodeKind.TEST)
    assert fragment.entry == "MAIN/0.body.0"
    assert (
        Edge(source="MAIN/0.body.0", target=test_node.id, kind=EdgeKind.FLOW)
        in fragment.edges
    )
    assert (
        Edge(source=test_node.id, target="MAIN/0.body.0", kind=EdgeKind.FALSE)
        in fragment.edges
    )
    assert [e.node_id for e in fragment.exits] == [test_node.id]
    assert [e.kind for e in fragment.exits] == [EdgeKind.TRUE]


def test_perform_times_is_a_loop_whose_test_names_the_count(program_of) -> None:
    """The count is a field as often as a literal, and when it is a field the loop
    depends on it -- so it is a read on the test node."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "PERFORM",
                "perform_type": "TIMES",
                "times": {"kind": "ref", "name": "WS-COUNT"},
                "children": [_move("'F'", "WS-RESULT")],
            }
        ],
    )

    test_node = next(n for n in fragment.nodes if n.kind == NodeKind.TEST)
    assert (test_node.atom.left, test_node.atom.op) == ("WS-COUNT", "TIMES")
    assert test_node.reads == ("WS-COUNT",)


def test_perform_varying_initialises_steps_and_tests(program_of) -> None:
    """Three extra nodes, and both assignments to the loop variable are real
    definitions -- a query for what writes the index has to find them."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "PERFORM",
                "perform_type": "VARYING",
                "varying_var": {"kind": "ref", "name": "WS-IDX"},
                "varying_from": {"kind": "lit", "value": "1"},
                "varying_by": {"kind": "lit", "value": "1"},
                "until": _cond("WS-IDX", "10"),
                "children": [_move("'F'", "WS-RESULT")],
            }
        ],
    )

    by_id = {node.id: node for node in fragment.nodes}
    assert by_id["MAIN/0#init"].writes == ("WS-IDX",)
    assert by_id["MAIN/0#init"].reads == ("1",)
    assert by_id["MAIN/0#step"].writes == ("WS-IDX",)
    assert by_id["MAIN/0#step"].reads == ("WS-IDX", "1")
    assert fragment.entry == "MAIN/0#init"


def test_the_step_of_a_varying_loop_goes_back_to_the_test(program_of) -> None:
    fragment = _lower(
        program_of,
        [
            {
                "type": "PERFORM",
                "perform_type": "VARYING",
                "varying_var": {"kind": "ref", "name": "WS-IDX"},
                "varying_from": {"kind": "lit", "value": "1"},
                "varying_by": {"kind": "lit", "value": "1"},
                "until": _cond("WS-IDX", "10"),
                "children": [_move("'F'", "WS-RESULT")],
            }
        ],
    )

    test_node = next(n for n in fragment.nodes if n.kind == NodeKind.TEST)
    assert (
        Edge(source="MAIN/0#step", target=test_node.id, kind=EdgeKind.FLOW)
        in fragment.edges
    )


def test_a_loop_around_a_performed_paragraph_keeps_both(program_of) -> None:
    """PERFORM P UNTIL C is a loop whose body is a call, so the CALL node is inside
    the loop and the paragraph is still shared."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "PERFORM",
                "operands": ["1000-FIRST"],
                "perform_type": "UNTIL",
                "until": _cond("WS-EOF", "'Y'"),
            }
        ],
    )

    kinds = {node.kind for node in fragment.nodes}
    assert kinds == {NodeKind.TEST, NodeKind.CALL}
    call = next(n for n in fragment.nodes if n.kind == NodeKind.CALL)
    assert call.target == "1000-FIRST"


def test_perform_varying_with_test_after_runs_the_body_first(program_of) -> None:
    """TEST AFTER on VARYING makes the first iteration unconditional."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "PERFORM",
                "perform_type": "VARYING",
                "varying_var": {"kind": "ref", "name": "WS-IDX"},
                "varying_from": {"kind": "lit", "value": "1"},
                "varying_by": {"kind": "lit", "value": "1"},
                "until": _cond("WS-IDX", "10"),
                "test_before": False,
                "children": [_move("'F'", "WS-RESULT")],
            }
        ],
    )

    assert fragment.entry == "MAIN/0#init"
    init_edges = [e for e in fragment.edges if e.source == "MAIN/0#init"]
    assert len(init_edges) == 1
    assert init_edges[0].target == "MAIN/0.body.0"


def test_perform_varying_after_creates_nested_loops(program_of) -> None:
    """AFTER specs nest: the inner variable varies fastest."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "PERFORM",
                "perform_type": "VARYING",
                "varying_var": {"kind": "ref", "name": "WS-I"},
                "varying_from": {"kind": "lit", "value": "1"},
                "varying_by": {"kind": "lit", "value": "1"},
                "until": _cond("WS-I", "3"),
                "children": [_move("'F'", "WS-RESULT")],
                "after_specs": [
                    {
                        "varying_var": {"kind": "ref", "name": "WS-J"},
                        "varying_from": {"kind": "lit", "value": "1"},
                        "varying_by": {"kind": "lit", "value": "1"},
                        "until": _cond("WS-J", "5"),
                        "test_before": True,
                    }
                ],
            }
        ],
    )

    by_id = {node.id: node for node in fragment.nodes}
    assert by_id["MAIN/0.after.0#init"].writes == ("WS-J",)
    assert by_id["MAIN/0.after.0#step"].writes == ("WS-J",)
    inner_test = next(
        n for n in fragment.nodes if n.kind == NodeKind.TEST and "WS-J" in n.atom.text
    )
    assert inner_test.id.startswith("MAIN/0.after.0#loop")


def test_after_spec_nesting_direction_inner_step_to_inner_test(program_of) -> None:
    """The inner loop's step goes back to the inner test, and only the inner test's
    exit reaches the outer step."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "PERFORM",
                "perform_type": "VARYING",
                "varying_var": {"kind": "ref", "name": "WS-I"},
                "varying_from": {"kind": "lit", "value": "1"},
                "varying_by": {"kind": "lit", "value": "1"},
                "until": _cond("WS-I", "3"),
                "children": [_move("'F'", "WS-RESULT")],
                "after_specs": [
                    {
                        "varying_var": {"kind": "ref", "name": "WS-J"},
                        "varying_from": {"kind": "lit", "value": "1"},
                        "varying_by": {"kind": "lit", "value": "1"},
                        "until": _cond("WS-J", "5"),
                        "test_before": True,
                    }
                ],
            }
        ],
    )

    inner_test = next(
        n for n in fragment.nodes if n.kind == NodeKind.TEST and "WS-J" in n.atom.text
    )
    assert (
        Edge(source="MAIN/0.after.0#step", target=inner_test.id, kind=EdgeKind.FLOW)
        in fragment.edges
    )
    outer_test = next(
        n for n in fragment.nodes if n.kind == NodeKind.TEST and "WS-I" in n.atom.text
    )
    edges_from_inner_test_true = [
        e
        for e in fragment.edges
        if e.source == inner_test.id and e.kind == EdgeKind.TRUE
    ]
    assert edges_from_inner_test_true[0].target == "MAIN/0#step"


def test_a_perform_as_the_last_statement_returns_to_the_paragraph_end(asg_of) -> None:
    """When a PERFORM is the last statement, its RETURN edge goes to the
    paragraph's #end node."""
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "0000-MAIN",
                    "statements": [
                        {
                            "type": "PERFORM",
                            "operands": ["1000-FIRST"],
                        }
                    ],
                },
                {"name": "1000-FIRST", "statements": [_move("'A'", "WS-A")]},
            )
        )
    )

    return_edges = [
        e for e in cfg.successors(end_id("1000-FIRST")) if e.kind == EdgeKind.RETURN
    ]
    assert len(return_edges) == 1
    assert return_edges[0].target == end_id("0000-MAIN")


def test_a_paragraph_performed_from_two_places_gets_two_return_edges(asg_of) -> None:
    """The deliberate over-approximation: a paragraph performed from multiple
    places receives multiple RETURN edges."""
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "0000-MAIN",
                    "statements": [
                        {"type": "PERFORM", "operands": ["2000-SHARED"]},
                        _move("'A'", "WS-A"),
                    ],
                },
                {
                    "name": "1000-OTHER",
                    "statements": [
                        {"type": "PERFORM", "operands": ["2000-SHARED"]},
                        _move("'B'", "WS-B"),
                    ],
                },
                {"name": "2000-SHARED", "statements": [_move("'S'", "WS-S")]},
            )
        )
    )

    return_edges = [
        e for e in cfg.successors(end_id("2000-SHARED")) if e.kind == EdgeKind.RETURN
    ]
    assert len(return_edges) == 2
    targets = {e.target for e in return_edges}
    assert targets == {"0000-MAIN/1", "1000-OTHER/1"}


def test_a_perform_that_can_never_return_keeps_its_way_on(asg_of) -> None:
    """Nothing reaches the range's end, so by the graph the statement after is dead --
    but the graph can be wrong, so the PERFORM keeps its FLOW edge and no resume."""
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "0000-MAIN",
                    "statements": [
                        {"type": "PERFORM", "operands": ["1000-STOP"]},
                        _move("'F'", "WS-RESULT"),
                    ],
                },
                {"name": "1000-STOP", "statements": [{"type": "GOBACK"}]},
            )
        )
    )

    assert [(e.target, e.kind) for e in cfg.successors("0000-MAIN/0")] == [
        (label_id("1000-STOP"), EdgeKind.PERFORM),
        ("0000-MAIN/1", EdgeKind.FLOW),
    ]
    assert cfg.node("0000-MAIN/0").resume == ""
