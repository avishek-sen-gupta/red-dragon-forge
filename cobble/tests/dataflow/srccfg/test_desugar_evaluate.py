"""EVALUATE is a guard chain: a WHEN is reached only when every earlier WHEN
failed. That is the same FALSE-edge chaining OR uses, so the reaching condition of
a branch's body already carries the negation of the branches above it -- which is
the part a per-branch guard stack loses.
"""

from __future__ import annotations

from cobble.dataflow.depgraph.flows import program_context

from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind, NodeKind
from cobble.dataflow.srccfg.conditions import condition_index
from cobble.dataflow.srccfg.desugar import Ctx, lower_statements


def _ctx(asg) -> Ctx:
    return Ctx(
        program=asg.program_id,
        paragraph="MAIN",
        flows=program_context(asg),
        index=condition_index(asg),
    )


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _cfg(program_of, statements: list[dict]) -> Cfg:
    asg = program_of(statements)
    fragment = lower_statements(asg.paragraphs[0].statements, _ctx(asg), "")
    return Cfg(program="PROGA", nodes=fragment.nodes, edges=fragment.edges)


def _evaluate(*branches: dict, subject: str = "WS-TYPE-B") -> dict:
    return {"type": "EVALUATE", "subject": subject, "children": list(branches)}


def test_a_when_value_becomes_an_equality_on_the_subject(program_of) -> None:
    """The ASG hands EVALUATE <subject> WHEN <value> over already prefixed as the
    string "<subject> = <value>", so the parts have to be recovered from text --
    without that, the subject is not a dependency of anything in the branch."""
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {
                    "type": "WHEN",
                    "condition": "WS-TYPE-B = 'G'",
                    "children": [_move("'F'", "WS-RESULT")],
                }
            )
        ],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert (test_node.atom.left, test_node.atom.op, test_node.atom.right) == (
        "WS-TYPE-B",
        "==",
        "'G'",
    )


def test_a_second_when_is_reached_only_by_the_first_ones_false_edge(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {
                    "type": "WHEN",
                    "condition": "WS-TYPE-B = 'G'",
                    "children": [_move("'F'", "WS-RESULT")],
                },
                {
                    "type": "WHEN",
                    "condition": "WS-TYPE-B = 'H'",
                    "children": [_move("'J'", "WS-RESULT")],
                },
            )
        ],
    )

    first, second = (n.id for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert [
        (e.target, e.kind) for e in cfg.successors(first) if e.kind is EdgeKind.FALSE
    ] == [(second, EdgeKind.FALSE)]


def test_when_other_is_the_last_false_arm(program_of) -> None:
    """WHEN OTHER carries the negation of every branch above it, and that is the
    only place it is recorded -- the branch itself has no condition of its own."""
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {
                    "type": "WHEN",
                    "condition": "WS-TYPE-B = 'G'",
                    "children": [_move("'F'", "WS-RESULT")],
                },
                {"type": "WHEN_OTHER", "children": [_move("'Z'", "WS-RESULT")]},
            )
        ],
    )

    other = cfg.node("MAIN/0.when.1.0")
    assert other.writes == ("WS-RESULT",)
    assert [e.kind for e in cfg.predecessors(other.id)] == [EdgeKind.FALSE]


def test_every_branch_body_continues_into_the_statement_after_the_evaluate(
    program_of,
) -> None:
    """COBOL EVALUATE does not fall through: each branch ends the statement. So
    every body's exit, and the last WHEN's FALSE edge when there is no WHEN OTHER,
    lead to whatever follows END-EVALUATE."""
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {
                    "type": "WHEN",
                    "condition": "WS-TYPE-B = 'G'",
                    "children": [_move("'F'", "WS-RESULT")],
                },
                {
                    "type": "WHEN",
                    "condition": "WS-TYPE-B = 'H'",
                    "children": [_move("'J'", "WS-RESULT")],
                },
            ),
            _move("WS-RESULT", "WS-COPY"),
        ],
    )

    assert {e.source for e in cfg.predecessors("MAIN/1")} == {
        "MAIN/0.when.0.0",
        "MAIN/0.when.1.0",
        "MAIN/0.when.1#test",
    }


def test_a_structured_condition_under_evaluate_true_lowers_like_an_if(
    program_of,
) -> None:
    """EVALUATE TRUE WHEN A AND B is a full conditional expression, and the ASG
    gives it as the same dict an IF carries -- so it must lower to a TEST chain,
    not to one opaque atom."""
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {
                    "type": "WHEN",
                    "condition": {
                        "op": "AND",
                        "left": {
                            "not": False,
                            "relation": {
                                "left": {"kind": "ref", "name": "WS-FLAG-A"},
                                "op": "==",
                                "right": {"kind": "lit", "value": "'Y'"},
                            },
                        },
                        "right": {
                            "not": False,
                            "relation": {
                                "left": {"kind": "ref", "name": "WS-TYPE-B"},
                                "op": "==",
                                "right": {"kind": "lit", "value": "'G'"},
                            },
                        },
                    },
                    "children": [_move("'F'", "WS-RESULT")],
                },
                subject="TRUE",
            )
        ],
    )

    assert len([n for n in cfg.nodes if n.kind == NodeKind.TEST]) == 2


def test_a_when_thru_becomes_one_range_atom(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {
                    "type": "WHEN",
                    "condition": "WS-TYPE-B = 'A'",
                    "condition_thru": "'M'",
                    "children": [_move("'F'", "WS-RESULT")],
                }
            )
        ],
    )

    atom = next(n for n in cfg.nodes if n.kind == NodeKind.TEST).atom
    assert (atom.left, atom.op, atom.right) == ("WS-TYPE-B", "RANGE", "'A' THRU 'M'")


def test_also_conditions_are_a_conjunction_within_the_branch(program_of) -> None:
    """WHEN a ALSO b holds only if both hold, so within the branch the two tests
    chain on the TRUE edge -- and both FALSE edges leave for the next branch."""
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {
                    "type": "WHEN",
                    "condition": "WS-TYPE-B = 'G'",
                    "also_conditions": ["WS-FLAG-A = 'Y'"],
                    "children": [_move("'F'", "WS-RESULT")],
                },
                {"type": "WHEN_OTHER", "children": [_move("'Z'", "WS-RESULT")]},
            )
        ],
    )

    tests = [n.id for n in cfg.nodes if n.kind == NodeKind.TEST]
    assert len(tests) == 2
    other = "MAIN/0.when.1.0"
    assert {e.source for e in cfg.predecessors(other)} == set(tests)


def test_when_any_is_an_always_true_test_that_still_occupies_a_node(
    program_of,
) -> None:
    """WHEN ANY matches unconditionally. Keeping a node means the branch above it
    still records its own negation on the path here, and a report can say which
    branch fired."""
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {
                    "type": "WHEN",
                    "condition": "ANY",
                    "children": [_move("'F'", "WS-RESULT")],
                }
            )
        ],
    )

    atom = next(n for n in cfg.nodes if n.kind == NodeKind.TEST).atom
    assert atom.text == "ANY"
    assert atom.op == ""


def test_an_evaluate_with_no_branches_lowers_to_nothing(program_of) -> None:
    cfg = _cfg(program_of, [_evaluate()])

    assert cfg.nodes == ()
