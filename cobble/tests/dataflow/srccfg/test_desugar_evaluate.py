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


def _parts(cfg: Cfg) -> list[tuple[str, str, str]]:
    return [
        (n.atom.left, n.atom.op, n.atom.right)
        for n in cfg.nodes
        if n.kind == NodeKind.TEST
    ]


def test_a_when_value_becomes_an_equality_on_the_subject(program_of) -> None:
    """The parse cache holds EVALUATE <subject> WHEN <value> as the bare value
    under the statement's subject -- the subject is joined to it only when
    RedDragon lowers for execution. Without the subject the branch depends on
    nothing, and a value like 0 reads as a condition name."""
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {
                    "type": "WHEN",
                    "condition": "0",
                    "children": [_move("'F'", "WS-RESULT")],
                },
                subject="WS-RESP-CD",
            )
        ],
    )

    assert _parts(cfg) == [("WS-RESP-CD", "==", "0")]


def test_a_when_constant_name_is_compared_with_the_subject(program_of) -> None:
    """EVALUATE EIBAID WHEN DFHENTER compares two names; DFHENTER is the value,
    not a level-88 condition."""
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {
                    "type": "WHEN",
                    "condition": "DFHENTER",
                    "children": [_move("'F'", "WS-RESULT")],
                },
                subject="EIBAID",
            )
        ],
    )

    assert _parts(cfg) == [("EIBAID", "==", "DFHENTER")]


def test_a_when_dfhresp_value_is_compared_with_the_subject(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {
                    "type": "WHEN",
                    "condition": {"kind": "dfhresp", "condition": "NORMAL"},
                    "children": [_move("'F'", "WS-RESULT")],
                },
                subject="WS-RESP-CD",
            )
        ],
    )

    assert _parts(cfg) == [("WS-RESP-CD", "==", "DFHRESP(NORMAL)")]


def test_a_bare_when_value_with_thru_is_a_range_on_the_subject(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {
                    "type": "WHEN",
                    "condition": "'A'",
                    "condition_thru": "'M'",
                    "children": [_move("'F'", "WS-RESULT")],
                }
            )
        ],
    )

    assert _parts(cfg) == [("WS-TYPE-B", "RANGE", "'A' THRU 'M'")]


def test_each_also_value_is_compared_with_its_own_subject(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            {
                "type": "EVALUATE",
                "subject": "WS-TYPE-B",
                "also_subjects": ["WS-FLAG-A"],
                "children": [
                    {
                        "type": "WHEN",
                        "condition": "'G'",
                        "also_conditions": ["'Y'"],
                        "children": [_move("'F'", "WS-RESULT")],
                    }
                ],
            }
        ],
    )

    assert _parts(cfg) == [("WS-TYPE-B", "==", "'G'"), ("WS-FLAG-A", "==", "'Y'")]


def test_under_evaluate_true_a_when_name_stays_a_condition_name(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {
                    "type": "WHEN",
                    "condition": "INPUT-ERROR",
                    "children": [_move("'F'", "WS-RESULT")],
                },
                subject="TRUE",
            )
        ],
    )

    assert _parts(cfg) == [("INPUT-ERROR", "88", "")]


def test_a_when_already_joined_to_its_subject_is_not_joined_twice(program_of) -> None:
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

    assert _parts(cfg) == [("WS-TYPE-B", "==", "'G'")]


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


def test_an_any_among_also_values_is_no_test_at_all(program_of) -> None:
    """ANY matches whatever its subject holds, so beside a real comparison it adds
    nothing but a FALSE edge that can never fire. The real comparisons keep their
    own ALSO slots."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "EVALUATE",
                "subject": "WS-TYPE-B",
                "also_subjects": ["WS-FLAG-A"],
                "children": [
                    {
                        "type": "WHEN",
                        "condition": "'G'",
                        "also_conditions": ["ANY"],
                        "children": [_move("'F'", "WS-RESULT")],
                    },
                    {
                        "type": "WHEN",
                        "condition": "ANY",
                        "also_conditions": ["'Y'"],
                        "children": [_move("'E'", "WS-RESULT")],
                    },
                    {"type": "WHEN_OTHER", "children": [_move("'O'", "WS-RESULT")]},
                ],
            }
        ],
    )

    assert [
        (n.id, n.atom.left, n.atom.op, n.atom.right)
        for n in cfg.nodes
        if n.kind == NodeKind.TEST
    ] == [
        ("MAIN/0.when.0#test", "WS-TYPE-B", "==", "'G'"),
        ("MAIN/0.when.1#test.A1", "WS-FLAG-A", "==", "'Y'"),
    ]
    assert {(e.target, e.kind) for e in cfg.successors("MAIN/0.when.0#test")} == {
        ("MAIN/0.when.0.0", EdgeKind.TRUE),
        ("MAIN/0.when.1#test.A1", EdgeKind.FALSE),
    }


def test_a_stacked_when_reaches_its_one_body_from_either_condition(
    program_of,
) -> None:
    """WHEN 1 WHEN 2 <body>: the second condition is tried when the first fails,
    as OR chains, and either one's TRUE edge enters the single body."""
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {
                    "type": "WHEN",
                    "condition": "1",
                    "alternatives": [{"type": "WHEN", "condition": "2"}],
                    "children": [_move("'F'", "WS-RESULT")],
                },
                {"type": "WHEN_OTHER", "children": [_move("'O'", "WS-OTHER")]},
            )
        ],
    )
    first, second = (n.id for n in cfg.nodes if n.kind == NodeKind.TEST)
    body = next(n.id for n in cfg.nodes if "WS-RESULT" in n.writes)
    other = next(n.id for n in cfg.nodes if "WS-OTHER" in n.writes)

    assert (
        _parts(cfg),
        {(e.source, e.kind) for e in cfg.predecessors(second)},
        {(e.source, e.kind) for e in cfg.predecessors(body)},
        {(e.source, e.kind) for e in cfg.predecessors(other)},
    ) == (
        [("WS-TYPE-B", "==", "1"), ("WS-TYPE-B", "==", "2")],
        {(first, EdgeKind.FALSE)},
        {(first, EdgeKind.TRUE), (second, EdgeKind.TRUE)},
        {(second, EdgeKind.FALSE)},
    )
