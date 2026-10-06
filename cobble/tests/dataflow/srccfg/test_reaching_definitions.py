"""Which write does a read see.

A gen/kill fixpoint rather than a per-path walk: the same definition reached by four
paths is one definition, and answering per path would report it four times with four
guards -- guards are a separate lookup, joined when a query asks for them.
"""

from __future__ import annotations

from cobol_asg.asg_types import CobolASG

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.cfg import Atom
from cobble.dataflow.srccfg.conditions import CLASS, IN
from cobble.dataflow.srccfg.dataflow import (
    Definition,
    condition_operands,
    definitions_of,
    reaching_definitions,
    readers_of,
    writers_of,
)


def _asg(paragraphs: list[dict]) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict({"program_id": "PROGA", "paragraphs": paragraphs})


def _move(value: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": value}, {"name": target}]}


def _if(condition: dict, then: list[dict], otherwise: list[dict]) -> dict:
    return {
        "type": "IF",
        "condition": condition,
        "children": then,
        "else_children": otherwise,
    }


def _rel(left: str, op: str, right: str) -> dict:
    return {
        "not": False,
        "relation": {
            "left": {"kind": "ref", "name": left},
            "op": op,
            "right": {"kind": "lit", "value": right},
        },
    }


def test_a_write_is_a_definition_at_its_own_node() -> None:
    cfg = build_program(
        _asg([{"name": "MAIN", "statements": [_move("'A'", "WS-FLAG-A")]}])
    )

    generated = definitions_of(cfg)

    assert Definition(node="MAIN/0", field="WS-FLAG-A") in generated["MAIN/0"]


def test_a_nodes_own_write_does_not_reach_its_own_entry() -> None:
    """The in-set is what a read on this node sees, and MOVE WS-X TO WS-X must read
    the previous write, not itself."""
    cfg = build_program(
        _asg([{"name": "MAIN", "statements": [_move("'A'", "WS-FLAG-A")]}])
    )

    assert reaching_definitions(cfg)["MAIN/0"] == frozenset()


def test_a_later_read_sees_the_earlier_write() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _move("'A'", "WS-FLAG-A"),
                        _move("WS-FLAG-A", "WS-RESULT"),
                    ],
                }
            ]
        )
    )

    assert (
        Definition(node="MAIN/0", field="WS-FLAG-A")
        in reaching_definitions(cfg)["MAIN/1"]
    )


def test_a_second_write_on_the_same_path_kills_the_first() -> None:
    """Without the kill, a derivation lists every write to a field ever, and the
    commonest COBOL shape -- initialise then overwrite -- reads as two sources."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _move("'A'", "WS-FLAG-A"),
                        _move("'B'", "WS-FLAG-A"),
                        _move("WS-FLAG-A", "WS-RESULT"),
                    ],
                }
            ]
        )
    )

    reaching = reaching_definitions(cfg)["MAIN/2"]

    assert Definition(node="MAIN/1", field="WS-FLAG-A") in reaching
    assert Definition(node="MAIN/0", field="WS-FLAG-A") not in reaching


def test_a_write_on_one_arm_only_does_not_kill_the_write_before_the_if() -> None:
    """The join is a union, so a read after a conditional overwrite sees both -- and
    the question "which one" is what the guards answer."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _move("'A'", "WS-FLAG-A"),
                        _if(
                            _rel("WS-OTHER", "=", "'Y'"),
                            [_move("'B'", "WS-FLAG-A")],
                            [],
                        ),
                        _move("WS-FLAG-A", "WS-RESULT"),
                    ],
                }
            ]
        )
    )
    reader = next(node.id for node in cfg.nodes if "WS-RESULT" in node.writes)

    fields = {d.field for d in reaching_definitions(cfg)[reader]}
    writers = {
        d.node for d in reaching_definitions(cfg)[reader] if d.field == "WS-FLAG-A"
    }

    assert "WS-FLAG-A" in fields
    assert len(writers) == 2


def test_a_write_on_both_arms_kills_the_write_before_the_if() -> None:
    """A kill on every path is a kill, and reporting the pre-IF write here would put
    a dead source in every derivation of this field."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _move("'A'", "WS-FLAG-A"),
                        _if(
                            _rel("WS-OTHER", "=", "'Y'"),
                            [_move("'B'", "WS-FLAG-A")],
                            [_move("'C'", "WS-FLAG-A")],
                        ),
                        _move("WS-FLAG-A", "WS-RESULT"),
                    ],
                }
            ]
        )
    )
    reader = next(node.id for node in cfg.nodes if "WS-RESULT" in node.writes)

    writers = {
        d.node for d in reaching_definitions(cfg)[reader] if d.field == "WS-FLAG-A"
    }

    assert "MAIN/0" not in writers
    assert len(writers) == 2


def test_a_definition_reaches_a_performed_paragraph() -> None:
    """M1: The write and the read are in different paragraphs. USE-IT comes before
    MAIN in source order so fallthrough cannot reach it; only PERFORM/RETURN can."""
    cfg = build_program(
        _asg(
            [
                {"name": "USE-IT", "statements": [_move("WS-FLAG-A", "WS-RESULT")]},
                {
                    "name": "MAIN",
                    "statements": [
                        _move("'A'", "WS-FLAG-A"),
                        {"type": "PERFORM", "operands": ["USE-IT"]},
                    ],
                },
            ]
        )
    )
    reader = next(node.id for node in cfg.nodes if "WS-RESULT" in node.writes)

    assert (
        Definition(node="MAIN/0", field="WS-FLAG-A")
        in reaching_definitions(cfg)[reader]
    )


def test_a_write_inside_a_performed_paragraph_reaches_after_the_call() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        {"type": "PERFORM", "operands": ["SET-IT"]},
                        _move("WS-FLAG-A", "WS-RESULT"),
                    ],
                },
                {"name": "SET-IT", "statements": [_move("'A'", "WS-FLAG-A")]},
            ]
        )
    )
    reader = next(node.id for node in cfg.nodes if "WS-RESULT" in node.writes)

    assert {
        d.node for d in reaching_definitions(cfg)[reader] if d.field == "WS-FLAG-A"
    } == {"SET-IT/0"}


def test_a_loop_reaches_a_fixpoint_rather_than_iterating_forever() -> None:
    """M2: A loop must converge. At STEP/0 (MOVE WS-FLAG-A TO WS-PREV), the
    definitions of WS-FLAG-A should include STEP/1 from the back-edge."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        {
                            "type": "PERFORM",
                            "operands": ["STEP"],
                            "spec": {
                                "kind": "until",
                                "condition": _rel("WS-FLAG-A", "=", "'Y'"),
                                "test_before": True,
                            },
                        }
                    ],
                },
                {
                    "name": "STEP",
                    "statements": [
                        _move("WS-FLAG-A", "WS-PREV"),
                        _move("'Y'", "WS-FLAG-A"),
                    ],
                },
            ]
        )
    )

    result = reaching_definitions(cfg)
    assert {(d.node, d.field) for d in result["STEP/0"]} == {
        ("STEP/0", "WS-PREV"),
        ("STEP/1", "WS-FLAG-A"),
    }


def test_writers_of_lists_every_node_that_writes_a_field_in_source_order() -> None:
    """The first query anyone asks. Source order, because a reader compares it
    against the listing."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _move("'A'", "WS-FLAG-A"),
                        _move("'B'", "WS-FLAG-A"),
                    ],
                }
            ]
        )
    )

    assert writers_of(cfg, "WS-FLAG-A") == ("MAIN/0", "MAIN/1")


def test_readers_of_lists_every_node_that_reads_a_field_in_source_order() -> None:
    """The mirror of writers_of, and the forward half of a provenance report rests
    on it: a field read twice must report both, in the order the listing shows."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _move("WS-SRC", "WS-ONE"),
                        _move("WS-SRC", "WS-TWO"),
                    ],
                }
            ]
        )
    )

    assert readers_of(cfg, "WS-SRC") == ("MAIN/0", "MAIN/1")


def test_a_field_that_only_decides_a_branch_is_still_a_reader() -> None:
    """A TEST keeps its operands in the atom, not in node.reads. Searching reads
    alone reports a field that guards every write in the member as read nowhere --
    the opposite of true, and worst for exactly the flags worth asking about."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _if(
                            _rel("WS-FLAG-A", "=", "'Y'"),
                            [_move("'B'", "WS-RESULT")],
                            [],
                        )
                    ],
                }
            ]
        )
    )

    assert readers_of(cfg, "WS-FLAG-A") == ("MAIN/0#test",)


def test_a_subscripted_read_answers_a_query_for_the_base_name() -> None:
    """Base-name matched like writers_of, so the two halves of a report agree on
    what counts as the same field."""
    cfg = build_program(
        _asg([{"name": "MAIN", "statements": [_move("WS-TAB(1)", "WS-RESULT")]}])
    )

    assert readers_of(cfg, "WS-TAB") == ("MAIN/0",)


def test_condition_operands_reports_both_sides_of_a_relation() -> None:
    cfg_atom = Atom(text="WS-A = WS-B", left="WS-A", op="=", right="WS-B")

    assert condition_operands(cfg_atom) == ("WS-A", "WS-B")


def test_condition_operands_drops_the_right_of_a_value_operator() -> None:
    """IS NUMERIC puts a class name on the right, and an 88 its list of VALUEs.
    Harvesting those reports NUMERIC as a field the member never wrote, which
    spends the credibility of that line where it is genuinely true."""
    assert condition_operands(
        Atom(text="WS-A IS NUMERIC", left="WS-A", op=CLASS, right="NUMERIC")
    ) == ("WS-A",)
    assert condition_operands(
        Atom(text="WS-A IN ('Y')", left="WS-A", op=IN, right="'Y'")
    ) == ("WS-A",)


def test_condition_operands_drops_the_right_of_a_synthetic_left() -> None:
    """The right of %HANDLER[ANY] RAISED is the state being tested for, not a
    field. The left is kept -- whatever the test guards does depend on it -- and
    the caller labels it rather than claiming the member never wrote it."""
    assert condition_operands(
        Atom(text="%HANDLER[ANY] RAISED", left="%HANDLER[ANY]", op="", right="RAISED")
    ) == ("%HANDLER[ANY]",)


def test_a_long_straight_line_reaches_fixpoint_without_exhausting_time() -> None:
    """R33: Measure the Jacobi fixpoint on 400 sequential writes. A definition needs
    one sweep per hop, so this costs O(N) sweeps at O(N × |defs|) each. The number
    may be bad — that's for follow-up — but it must be measured."""
    import time

    statements = [
        _move(f"'{chr(65 + i % 26)}'", f"WS-FIELD-{i:03d}") for i in range(400)
    ]
    cfg = build_program(_asg([{"name": "MAIN", "statements": statements}]))

    start = time.perf_counter()
    result = reaching_definitions(cfg)
    elapsed = time.perf_counter() - start

    # Verify correctness: the last node sees only the immediately preceding definitions
    last_node = f"MAIN/{len(statements) - 1}"
    assert last_node in result
    # Each field should have exactly one reaching definition at the last node
    assert len(result[last_node]) == len(statements) - 1

    print(f"\n400-MOVE fixpoint wall-clock: {elapsed:.4f}s")
    assert elapsed < 30.0, f"Fixpoint took {elapsed:.2f}s, expecting under 30s"


def test_a_subscripted_write_is_visible_to_a_read_of_the_base_name() -> None:
    """I1: MOVE 'A' TO WS-TAB(1) generates a definition that writers_of('WS-TAB')
    finds and that reaches the read of WS-TAB."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _move("'A'", "WS-TAB(1)"),
                        _move("WS-TAB", "WS-RESULT"),
                    ],
                }
            ]
        )
    )

    assert writers_of(cfg, "WS-TAB") == ("MAIN/0",)
    assert reaching_definitions(cfg)["MAIN/1"] == frozenset(
        {Definition(node="MAIN/0", field="WS-TAB(1)")}
    )


def test_a_reference_modified_write_is_visible_to_a_read_of_the_base_name() -> None:
    """I1: MOVE 'X' TO WS-FIELD(1:4) generates a definition that writers_of finds
    by base name and that reaches the read of WS-FIELD."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _move("'X'", "WS-FIELD(1:4)"),
                        _move("WS-FIELD", "WS-RESULT"),
                    ],
                }
            ]
        )
    )

    assert writers_of(cfg, "WS-FIELD") == ("MAIN/0",)
    assert reaching_definitions(cfg)["MAIN/1"] == frozenset(
        {Definition(node="MAIN/0", field="WS-FIELD(1:4)")}
    )


def test_a_subscripted_write_does_not_kill_the_base_name() -> None:
    """I1: A write to WS-TAB(1) does not kill WS-TAB or WS-TAB(2). Over-approximate
    on gen, never on kill."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _move("'A'", "WS-TAB"),
                        _move("'B'", "WS-TAB(1)"),
                        _move("WS-TAB", "WS-RESULT"),
                    ],
                }
            ]
        )
    )

    assert reaching_definitions(cfg)["MAIN/2"] == frozenset(
        {
            Definition(node="MAIN/0", field="WS-TAB"),
            Definition(node="MAIN/1", field="WS-TAB(1)"),
        }
    )
