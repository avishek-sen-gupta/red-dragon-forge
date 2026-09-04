"""GO TO. 11% of paragraphs are never PERFORMed and hold 5% of assignments; this
is how they are reached, and a pass that cannot see it reports those assignments as
unreachable or as unguarded."""

from __future__ import annotations

from cobble.dataflow.depgraph.flows import program_context

from cobble.dataflow.srccfg.cfg import NodeKind
from cobble.dataflow.srccfg.conditions import condition_index
from cobble.dataflow.srccfg.desugar import (
    DISPATCH_TRANSFER,
    GOTO_TRANSFER,
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


def _lower(program_of, statements: list[dict]):
    asg = program_of(statements)
    return lower_statements(asg.paragraphs[0].statements, _ctx(asg), "")


def test_a_simple_goto_names_its_target_and_leaves_no_exit(program_of) -> None:
    """No exit is the point: the statement after a GO TO is not reachable from it,
    and wiring one would make every assignment below look guarded by nothing."""
    fragment = _lower(
        program_of,
        [{"type": "GOTO", "form": "simple", "target": {"paragraph": "9999-EXIT"}}],
    )

    node = fragment.nodes[0]
    assert (node.kind, node.transfer, node.target) == (
        NodeKind.CALL,
        GOTO_TRANSFER,
        "9999-EXIT",
    )
    assert fragment.exits == ()


def test_a_statement_after_a_goto_is_left_unreachable(program_of) -> None:
    fragment = _lower(
        program_of,
        [
            {"type": "GOTO", "form": "simple", "target": {"paragraph": "9999-EXIT"}},
            {"type": "MOVE", "operands": [{"name": "'F'"}, {"name": "WS-RESULT"}]},
        ],
    )

    assert fragment.edges == ()
    assert [node.id for node in fragment.nodes] == ["MAIN/0", "MAIN/1"]


def test_a_computed_goto_emits_one_node_per_target(program_of) -> None:
    """GO TO p1 p2 DEPENDING ON i selects by index. Which target is taken depends
    on the index field, so the index is a read and every target is a possibility --
    an over-approximation the spec takes deliberately."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "GOTO",
                "form": "computed",
                "targets": [{"paragraph": "1000-A"}, {"paragraph": "2000-B"}],
                "index": {"name": "WS-IDX"},
            }
        ],
    )

    dispatch = fragment.nodes[0]
    assert (dispatch.transfer, dispatch.reads) == (DISPATCH_TRANSFER, ("WS-IDX",))
    assert [n.target for n in fragment.nodes[1:]] == ["1000-A", "2000-B"]
    assert [n.id for n in fragment.nodes[1:]] == ["MAIN/0#goto.0", "MAIN/0#goto.1"]


def test_a_computed_goto_falls_through_when_the_index_is_out_of_range(
    program_of,
) -> None:
    """An index outside 1..N is not an error in COBOL: control continues with the
    next statement. So the dispatch node keeps a FLOW exit even though each branch
    has none."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "GOTO",
                "form": "computed",
                "targets": [{"paragraph": "1000-A"}],
                "index": {"name": "WS-IDX"},
            }
        ],
    )

    assert [e.node_id for e in fragment.exits] == ["MAIN/0"]


def test_an_altered_goto_is_an_unresolved_transfer_not_a_silence(program_of) -> None:
    """GO TO with no operand is retargeted by ALTER at runtime. The transfer is
    real and its destination is unknown, which is a fact a report has to be able to
    state -- so the node exists with an empty target."""
    fragment = _lower(program_of, [{"type": "GOTO", "form": "altered"}])

    node = fragment.nodes[0]
    assert (node.kind, node.transfer, node.target) == (NodeKind.CALL, GOTO_TRANSFER, "")
    assert fragment.exits == ()


def test_a_goto_inside_an_if_arm_still_ends_that_arm(program_of) -> None:
    """The commonest shape in the corpus: a guarded early exit. The THEN arm must
    contribute no exit, so the statement after END-IF is reached only by the guard
    failing."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "IF",
                "condition": {
                    "not": False,
                    "relation": {
                        "left": {"kind": "ref", "name": "WS-FLAG-A"},
                        "op": "==",
                        "right": {"kind": "lit", "value": "'Y'"},
                    },
                },
                "children": [
                    {
                        "type": "GOTO",
                        "form": "simple",
                        "target": {"paragraph": "9999-EXIT"},
                    }
                ],
            },
            {"type": "MOVE", "operands": [{"name": "'F'"}, {"name": "WS-RESULT"}]},
        ],
    )

    into_last = {
        (e.source, e.kind.value) for e in fragment.edges if e.target == "MAIN/1"
    }
    assert into_last == {("MAIN/0#test", "FALSE")}
