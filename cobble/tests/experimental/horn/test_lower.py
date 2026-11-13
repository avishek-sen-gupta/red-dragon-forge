import json
from collections.abc import Callable, Iterator, Mapping, Sequence

import pytest
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.experimental.horn.answer import Answer
from cobble.dataflow.srccfg.cfg import EdgeKind, NodeKind
from cobble.experimental.horn.condition import (
    Condition,
    Digits,
    Entered,
    Op,
    Part,
    Took,
)
from cobble.experimental.horn.context import perform_edge, performed
from cobble.experimental.horn.every_test import EVERY_TEST
from cobble.experimental.horn.kept_tests import KeptTests
from cobble.experimental.horn.leading_to import leading_to
from cobble.experimental.horn.lower import lower
from cobble.experimental.horn.named_fields import NamedFields
from cobble.experimental.horn.outcome import Outcome
from cobble.experimental.horn.point import Point
from cobble.experimental.horn.program import Program, program_of
from cobble.experimental.horn.reaches import reaches
from cobol_asg.asg_types import CobolASG

Statement = Mapping[str, object]


def _clock() -> Callable[[], float]:
    ticks: Iterator[float] = iter(float(n) for n in range(1000))
    return lambda: next(ticks)


def _asg(
    paragraphs: Sequence[tuple[str, Sequence[Statement]]],
    data: Sequence[Statement],
    **extra: object,
) -> CobolASG:
    body = {
        "program_id": "PROGA",
        "data_fields": list(data),
        "paragraphs": [
            {"name": name, "statements": list(statements)}
            for name, statements in paragraphs
        ],
        **extra,
    }
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(json.loads(json.dumps(body)))


def _x(name: str, pic: str = "X", **extra: object) -> Statement:
    return {"name": name, "level": 1, "pic": pic, **extra}


def _flagged(name: str, conditions: Mapping[str, Sequence[str]]) -> Statement:
    return _x(
        name,
        conditions=[
            {"name": condition, "values": [{"from": value} for value in values]}
            for condition, values in conditions.items()
        ],
    )


def _move(value: str, target: str) -> Statement:
    return {"type": "MOVE", "operands": [{"name": value}, {"name": target}]}


def _move_literal(value: str, target: str) -> Statement:
    return {
        "type": "MOVE",
        "operands": [{"kind": "lit", "name": value}, {"name": target}],
    }


def _if(
    left: Mapping[str, object],
    right: str,
    then: Sequence[Statement],
    otherwise: Sequence[Statement] = (),
) -> Statement:
    return {
        "type": "IF",
        "condition": {
            "not": False,
            "relation": {
                "left": dict(left),
                "op": "==",
                "right": {"kind": "lit", "value": right},
            },
        },
        "children": list(then),
        "else_children": list(otherwise),
    }


def _ref(name: str) -> Mapping[str, object]:
    return {"kind": "ref", "name": name}


def _test(name: str, right: str, then: Sequence[Statement] = ()) -> Statement:
    return _if(_ref(name), right, then)


def _set_true(*conditions: str) -> Statement:
    return {
        "type": "SET",
        "set_type": "TO",
        "targets": [{"kind": "ref", "name": c} for c in conditions],
        "values": [{"kind": "lit", "value": "TRUE"}],
    }


def _perform(target: str, thru: str = "") -> Statement:
    return {"type": "PERFORM", "operands": [target], **({"thru": thru} if thru else {})}


def _goto(target: str) -> Statement:
    return {"type": "GOTO", "form": "simple", "target": {"paragraph": target}}


STOP: Statement = {"type": "STOP_RUN"}
X_OUT = _move("'x'", "X-OUT")
FIELDS = (_x("F"), _x("G"), _x("X-OUT"))


def _ask(
    paragraphs: Sequence[tuple[str, Sequence[Statement]]],
    data: Sequence[Statement],
    writer: str,
    conditions: Sequence[Condition] = (),
    watched: Sequence[str] = (),
    kept: KeptTests = EVERY_TEST,
    **extra: object,
) -> Answer:
    program = program_of(_asg(paragraphs, data, **extra))
    node = next(node.id for node in program.cfg.nodes if writer in node.writes)
    system = lower(program, watched, kept=kept)
    return reaches(system, Point("PROGA", node), conditions, _clock()).answer


def _f(op: Op, value: str) -> Condition:
    return Condition("F", op, value)


def test_a_test_constrains_the_values_after_it() -> None:
    program = [("MAIN", [_test("F", "'Y'", [X_OUT])])]

    assert (
        _ask(program, FIELDS, "X-OUT", [_f(Op.EQ, "'N'")]),
        _ask(program, FIELDS, "X-OUT", [_f(Op.EQ, "'Y'")]),
        _ask(program, FIELDS, "X-OUT", [_f(Op.NE, "'Y'")]),
    ) == (Answer.UNSAT, Answer.SAT, Answer.UNSAT)


def test_contradictory_tests_make_a_point_unreachable() -> None:
    program = [("MAIN", [_test("F", "'N'", [_test("F", "'Y'", [X_OUT])])])]

    assert _ask(program, FIELDS, "X-OUT") == Answer.UNSAT


def test_a_write_frees_the_field_it_overlaps() -> None:
    program = [("MAIN", [_test("F", "'Y'", [_move("G", "F"), X_OUT])])]

    assert _ask(program, FIELDS, "X-OUT", [_f(Op.EQ, "'N'")]) == Answer.SAT


def test_a_group_write_frees_the_flags_inside_it() -> None:
    record = {
        "name": "REC",
        "level": 1,
        "children": [
            {"name": "F", "level": 5, "pic": "X", "offset": 0},
            {"name": "H", "level": 5, "pic": "X", "offset": 1},
        ],
    }
    data = (record, _x("G", "X(2)"), _x("X-OUT"))
    program = [("MAIN", [_test("F", "'Y'", [_move("G", "REC"), X_OUT])])]

    assert _ask(program, data, "X-OUT", [_f(Op.EQ, "'N'")]) == Answer.SAT


def test_a_perform_returns_only_to_its_own_caller() -> None:
    data = (*FIELDS, _x("A-OUT"), _x("B-OUT"), _x("P-OUT"))
    program = [
        (
            "MAIN",
            [
                _test("F", "'Y'", [_perform("P"), _move("'a'", "A-OUT")]),
                _test("F", "'N'", [_perform("P"), _move("'b'", "B-OUT")]),
                STOP,
            ],
        ),
        ("P", [_test("F", "'Y'", [_move("'p'", "P-OUT")])]),
    ]

    assert (
        _ask(program, data, "B-OUT", [_f(Op.EQ, "'Y'")]),
        _ask(program, data, "B-OUT", [_f(Op.EQ, "'N'")]),
        _ask(program, data, "A-OUT", [_f(Op.EQ, "'Y'")]),
    ) == (Answer.UNSAT, Answer.SAT, Answer.SAT)


def test_a_thru_range_falls_through_inside_and_stops_at_its_end() -> None:
    data = (*FIELDS, _x("A-OUT"), _x("B-OUT"), _x("C-OUT"), _x("R-OUT"))
    program = [
        ("MAIN", [_perform("A", thru="B"), _move("'r'", "R-OUT"), STOP]),
        ("A", [_move("'a'", "A-OUT")]),
        ("B", [_move("'b'", "B-OUT")]),
        ("C", [_move("'c'", "C-OUT")]),
    ]

    assert (
        _ask(program, data, "B-OUT"),
        _ask(program, data, "R-OUT"),
        _ask(program, data, "C-OUT"),
    ) == (Answer.SAT, Answer.SAT, Answer.UNSAT)


def test_a_name_declared_twice_is_not_tracked() -> None:
    def record(name: str) -> Statement:
        return {
            "name": name,
            "level": 1,
            "children": [{"name": "D", "level": 5, "pic": "X", "offset": 0}],
        }

    data = (record("R1"), record("R2"), *FIELDS)
    program = [("MAIN", [_test("D", "'N'", [_test("D", "'Y'", [X_OUT])])])]

    assert _ask(program, data, "X-OUT") == Answer.SAT
    with pytest.raises(ValueError, match="^D is not a tracked field$"):
        _ask(program, data, "X-OUT", [Condition("D", Op.EQ, "'Y'")])


def test_a_goto_out_of_a_range_does_not_return_to_the_perform() -> None:
    data = (*FIELDS, _x("Q-OUT"), _x("R-OUT"))
    program = [
        ("MAIN", [_perform("P"), _move("'r'", "R-OUT"), STOP]),
        ("P", [_test("F", "'Y'", [_goto("Q")])]),
        ("Q", [_move("'q'", "Q-OUT")]),
    ]

    assert (
        _ask(program, data, "Q-OUT", [_f(Op.EQ, "'Y'")]),
        _ask(program, data, "R-OUT", [_f(Op.EQ, "'Y'")]),
        _ask(program, data, "R-OUT", [_f(Op.EQ, "'N'")]),
    ) == (Answer.SAT, Answer.UNSAT, Answer.SAT)


def test_a_perform_of_a_range_the_program_lacks_frees_every_tracked_byte() -> None:
    """The CFG keeps the edge past an unresolved PERFORM, and nothing says what
    the missing range did."""
    program = [("MAIN", [_test("F", "'Y'", [_perform("MISSING"), X_OUT])])]

    assert _ask(program, FIELDS, "X-OUT", [_f(Op.EQ, "'N'")]) == Answer.SAT


FLAGS = (
    _flagged("F", {"F-ON": ("'Y'",), "F-AB": ("'A'", "'B'")}),
    _x("G"),
    _x("X-OUT"),
)


def test_a_literal_move_sets_the_flag_exactly() -> None:
    program = [("MAIN", [_move_literal("'Y'", "F"), _test("F", "'Q'"), X_OUT])]

    assert (
        _ask(program, FIELDS, "X-OUT", [_f(Op.EQ, "'N'")]),
        _ask(program, FIELDS, "X-OUT", [_f(Op.EQ, "'Y'")]),
    ) == (Answer.UNSAT, Answer.SAT)


def test_a_figurative_move_fills_the_field() -> None:
    data = (_x("F3", "X(3)"), *FIELDS)
    program = [
        (
            "MAIN",
            [
                {
                    "type": "MOVE",
                    "operands": [
                        {"kind": "figurative", "name": "SPACES"},
                        {"name": "F3"},
                    ],
                },
                _test("F3", "'Q'"),
                X_OUT,
            ],
        )
    ]
    blank = Condition("F3", Op.EQ, "SPACES")
    low = Condition("F3", Op.EQ, "LOW-VALUES")

    assert (
        _ask(program, data, "X-OUT", [blank]),
        _ask(program, data, "X-OUT", [low]),
    ) == (
        Answer.SAT,
        Answer.UNSAT,
    )


def test_set_to_true_moves_the_first_value_and_set_names_each_condition_in_order() -> (
    None
):
    """SET F-ON F-AB TO TRUE moves 'Y' and then 'A', the first value of F-AB."""
    program = [("MAIN", [_set_true("F-ON", "F-AB"), _test("F", "'Q'"), X_OUT])]

    assert (
        _ask(program, FLAGS, "X-OUT", [_f(Op.EQ, "'A'")]),
        _ask(program, FLAGS, "X-OUT", [_f(Op.EQ, "'Y'")]),
    ) == (Answer.SAT, Answer.UNSAT)


def test_a_qualified_condition_sets_the_field_its_qualifier_names() -> None:
    def holder(record: str, flag: str, value: str) -> Statement:
        return {
            "name": record,
            "level": 1,
            "children": [
                {
                    "name": flag,
                    "level": 5,
                    "pic": "X",
                    "offset": 0,
                    "conditions": [{"name": "ON", "values": [{"from": value}]}],
                }
            ],
        }

    data = (holder("G1", "P1", "'1'"), holder("G2", "P2", "'2'"), _x("X-OUT"))
    target = {"kind": "ref", "name": "ON", "qualifiers": ["G2"]}
    set_on = {
        "type": "SET",
        "set_type": "TO",
        "targets": [target],
        "values": [{"kind": "lit", "value": "TRUE"}],
    }
    program = [("MAIN", [_test("P2", "'N'", [set_on, _test("P1", "'Q'"), X_OUT])])]

    assert (
        _ask(program, data, "X-OUT", [Condition("P2", Op.EQ, "'2'")]),
        _ask(program, data, "X-OUT", [Condition("P2", Op.EQ, "'N'")]),
    ) == (Answer.SAT, Answer.UNSAT)


def test_a_moved_literal_is_padded_and_truncated_to_the_field() -> None:
    data = (_x("F3", "X(3)"), _x("F2", "X(2)"), *FIELDS)
    program = [
        (
            "MAIN",
            [
                _move_literal("'Y'", "F3"),
                _move_literal("'ABCDE'", "F2"),
                _test("F3", "'Q'"),
                _test("F2", "'Q'"),
                X_OUT,
            ],
        )
    ]

    assert (
        _ask(program, data, "X-OUT", [Condition("F3", Op.EQ, "'Y  '")]),
        _ask(program, data, "X-OUT", [Condition("F3", Op.EQ, "'YYY'")]),
        _ask(program, data, "X-OUT", [Condition("F2", Op.NE, "'AB'")]),
    ) == (Answer.SAT, Answer.UNSAT, Answer.UNSAT)


def test_two_writes_to_one_field_in_one_statement_apply_in_order() -> None:
    """MOVE 'Y' TO F3 F3(2:1) leaves 'YY ': the second target is part of the first."""
    data = (_x("F3", "X(3)"), *FIELDS)
    part = {
        "name": "F3",
        "ref_mod_start": {"kind": "lit", "value": "2"},
        "ref_mod_length": {"kind": "lit", "value": "1"},
    }
    move = {
        "type": "MOVE",
        "operands": [{"kind": "lit", "name": "'Y'"}, {"name": "F3"}, part],
    }
    program = [("MAIN", [move, _test("F3", "'Q'"), X_OUT])]

    assert (
        _ask(program, data, "X-OUT", [Condition("F3", Op.EQ, "'YY '")]),
        _ask(program, data, "X-OUT", [Condition("F3", Op.EQ, "'Y  '")]),
    ) == (Answer.SAT, Answer.UNSAT)


def test_a_test_on_part_of_a_field_constrains_nothing() -> None:
    data = (_x("F3", "X(3)"), *FIELDS)
    part = {
        "kind": "ref",
        "name": "F3",
        "ref_mod_start": {"kind": "lit", "value": "1"},
        "ref_mod_length": {"kind": "lit", "value": "1"},
    }
    program = [("MAIN", [_test("F3", "'Q'"), _if(part, "'Y'", [X_OUT])])]

    assert _ask(program, data, "X-OUT", [Condition("F3", Op.EQ, "'YES'")]) == Answer.SAT


def test_a_sort_return_frees_the_field_it_reads_into() -> None:
    program = [
        (
            "MAIN",
            [
                _test(
                    "F",
                    "'Y'",
                    [
                        {
                            "type": "RETURN",
                            "file_name": "SF",
                            "into": {"name": "F"},
                            "at_end": [],
                            "not_at_end": [],
                        },
                        X_OUT,
                    ],
                )
            ],
        )
    ]

    assert (
        _ask(
            program,
            FIELDS,
            "X-OUT",
            [_f(Op.EQ, "'N'")],
            file_control=[{"file_name": "SF"}],
            file_fields=[
                {"level": 1, "name": "SF-REC", "pic": "X(8)", "fd_name": "SF"}
            ],
        )
        == Answer.SAT
    )


def test_a_statement_the_encoding_does_not_know_frees_every_tracked_byte() -> None:
    """UNSTRING is written by name in the CFG but its effect is not modelled; ENTRY
    is a statement nothing describes at all."""
    unstring = {
        "type": "UNSTRING",
        "source": {"name": "G"},
        "delimiters": [],
        "into": [{"target": {"name": "F"}}],
    }
    entry = {"type": "ENTRY", "name": "'ALT'", "using": []}
    unstrung = [("MAIN", [_test("F", "'Y'", [unstring, X_OUT])])]
    entered = [("MAIN", [_test("F", "'Y'", [entry, X_OUT])])]

    assert (
        _ask(unstrung, FIELDS, "X-OUT", [_f(Op.EQ, "'N'")]),
        _ask(entered, FIELDS, "X-OUT", [_f(Op.EQ, "'N'")]),
    ) == (Answer.SAT, Answer.SAT)


def test_a_file_statement_frees_the_file_status_field() -> None:
    data = (*FIELDS, _x("FS", "X(2)"))
    program = [
        (
            "MAIN",
            [
                _test(
                    "FS",
                    "'00'",
                    [{"type": "CLOSE", "files": [{"file_name": "IN-F"}]}, X_OUT],
                ),
            ],
        )
    ]

    assert (
        _ask(
            program,
            data,
            "X-OUT",
            [Condition("FS", Op.EQ, "'10'")],
            file_control=[{"file_name": "IN-F", "file_status_var": {"name": "FS"}}],
        )
        == Answer.SAT
    )


def test_a_justified_receiver_holds_the_literal_right_aligned() -> None:
    data = (_x("F3", "X(3)", justified_right=True), *FIELDS)
    program = [("MAIN", [_move_literal("'Y'", "F3"), _test("F3", "'Q'"), X_OUT])]

    assert _ask(program, data, "X-OUT", [Condition("F3", Op.EQ, "'  Y'")]) == Answer.SAT
    assert _ask(program, data, "X-OUT", [Condition("F3", Op.EQ, "'Y'")]) == Answer.UNSAT


def test_a_name_the_program_never_declares_is_not_tracked() -> None:
    program = [("MAIN", [_test("U", "'Y'", [X_OUT])])]

    with pytest.raises(ValueError, match="^U is not a tracked field$"):
        _ask(program, FIELDS, "X-OUT", [Condition("U", Op.EQ, "'Y'")])


def test_a_write_the_cfg_lists_but_the_transfer_misses_frees_the_field() -> None:
    """The CFG says FORMATTIME writes its output options; the transfer has no rule
    for it, so the node's own list is what frees the field."""
    data = (_x("D8", "X(8)"), _x("WS-T", "X(8)"), *FIELDS)
    formattime = {
        "type": "EXEC_CICS",
        "verb": "FORMATTIME",
        "options": {
            "ABSTIME": {"text": "WS-T", "is_literal": False},
            "MMDDYYYY": {"text": "D8", "is_literal": False},
        },
    }
    program = [("MAIN", [_test("D8", "'NONE    '", [formattime, X_OUT])])]

    assert _ask(program, data, "X-OUT", [Condition("D8", Op.EQ, "'01022026'")]) == (
        Answer.SAT
    )


def _group(name: str, *children: tuple[str, str, int]) -> Statement:
    return {
        "name": name,
        "level": 1,
        "children": [
            {"name": child, "level": 5, "pic": pic, "offset": offset}
            for child, pic, offset in children
        ],
    }


def test_a_copy_carries_the_source_bytes_along_a_chain() -> None:
    """MOVE 'AB' TO A; MOVE A TO B; MOVE B TO C; MOVE 'CD' TO A. Only C is watched:
    the closure tracks A and B, and the later write to A leaves C alone."""
    data = (_x("A", "X(2)"), _x("B", "X(2)"), _x("C", "X(2)"), *FIELDS)
    moves = [_move_literal("'AB'", "A"), _move("A", "B"), _move("B", "C")]
    program = [("MAIN", [*moves, _move_literal("'CD'", "A"), X_OUT])]

    def ask(condition: Condition, watched: Sequence[str]) -> Answer:
        return _ask(program, data, "X-OUT", [condition], watched)

    assert ask(Condition("C", Op.NE, "'AB'"), ("C",)) == Answer.UNSAT
    assert ask(Condition("C", Op.EQ, "'AB'"), ("C",)) == Answer.SAT
    assert ask(Condition("C", Op.NE, "A"), ("C", "A")) == Answer.SAT
    assert ask(Condition("C", Op.EQ, "A"), ("C", "A")) == Answer.UNSAT


def test_a_numeric_receiver_takes_the_senders_digits_not_its_zones() -> None:
    """MOVE N3 TO N2, PIC 9(3) into 9(2): N2's digits are N3's last two, while
    N2's zones are whatever the compiler writes, so N2's bytes need not equal any
    of N3's. MOVE G2 TO N4, G2 a group of two bytes, N4 PIC 9(2): a group move
    copies bytes, zones included."""
    data = (
        _x("N3", "9(3)"),
        _x("N2", "9(2)"),
        _group("G2", ("A2", "X(2)", 0)),
        _x("N4", "9(2)"),
        *FIELDS,
    )
    program = [("MAIN", [_move("N3", "N2"), _move("G2", "N4"), X_OUT])]
    watched = ("N2", "N3", "N4", "G2")

    def ask(condition: Condition) -> Answer:
        return _ask(program, data, "X-OUT", [condition], watched)

    assert ask(Condition(Digits("N2", 1, 2), Op.NE, Digits("N3", 2, 2))) == (
        Answer.UNSAT
    )
    assert ask(Condition(Digits("N2", 1, 2), Op.NE, Digits("N3", 1, 2))) == (Answer.SAT)
    assert ask(Condition("N2", Op.NE, Part("N3", 2, 2))) == Answer.SAT
    assert ask(Condition(Digits("N3", 1, 1), Op.NE, "'0'")) == Answer.SAT
    assert ask(Condition("N4", Op.NE, "G2")) == Answer.UNSAT


def test_every_target_of_one_move_takes_the_source_as_it_was() -> None:
    """MOVE A TO A2 B, where A2 is bytes 2-3 of A: B takes A as it was before the
    statement, not after A2 changed it."""
    data = (_group("A", ("A1", "X", 0), ("A2", "X(2)", 1)), _x("B", "X(3)"), *FIELDS)
    move = {
        "type": "MOVE",
        "operands": [{"name": "A"}, {"name": "A2"}, {"name": "B"}],
    }
    program = [("MAIN", [_move_literal("'ABC'", "A"), move, X_OUT])]

    def ask(condition: Condition) -> Answer:
        return _ask(program, data, "X-OUT", [condition], ("B",))

    assert ask(Condition("B", Op.NE, "'ABC'")) == Answer.UNSAT
    assert ask(Condition("B", Op.EQ, "'ABC'")) == Answer.SAT


def test_a_justified_receiver_longer_than_its_sender_frees_its_leading_bytes() -> None:
    """MOVE S TO R, S PIC X(1) just after P, R PIC X(3) JUSTIFIED RIGHT: R's last
    byte is S; its first two have no source byte, and are not P's bytes."""
    data = (
        _group("REC", ("P", "X(2)", 0), ("S", "X", 2)),
        _x("R", "X(3)", justified_right=True),
        *FIELDS,
    )
    moves = [_move_literal("'PP'", "P"), _move_literal("'Y'", "S"), _move("S", "R")]
    program = [("MAIN", [*moves, X_OUT])]

    def ask(condition: Condition) -> Answer:
        return _ask(program, data, "X-OUT", [condition], ("R", "S", "P"))

    assert ask(Condition("S", Op.NE, Part("R", 3, 1))) == Answer.UNSAT
    assert ask(Condition("R", Op.EQ, "'QQY'")) == Answer.SAT


def test_a_copy_from_a_computed_subscript_frees_the_target() -> None:
    data = (
        {
            "name": "TAB",
            "level": 1,
            "children": [
                {"name": "T", "level": 5, "pic": "X(2)", "offset": 0, "occurs": 3},
                {"name": "I", "level": 5, "pic": "9", "offset": 6},
            ],
        },
        _x("B", "X(2)"),
        *FIELDS,
    )
    move = {
        "type": "MOVE",
        "operands": [
            {"name": "T", "subscripts": [{"kind": "ref", "name": "I"}]},
            {"name": "B"},
        ],
    }
    program = [("MAIN", [_move_literal("'AB'", "B"), move, X_OUT])]

    assert (
        _ask(program, data, "X-OUT", [Condition("B", Op.NE, "'AB'")], ("B",))
        == Answer.SAT
    )


def test_a_copy_onto_its_own_bytes_frees_the_target() -> None:
    """MOVE 'ABC' TO A; MOVE A(1:2) TO A2, A2 bytes 2-3 of A. Sender and receiver
    share A's second byte, and COBOL leaves such a move's result undefined: a
    byte-at-a-time copy gives 'AAA', a copy from the bytes as found 'AAB'."""
    data = (_group("A", ("A1", "X", 0), ("A2", "X(2)", 1)), *FIELDS)
    move = {
        "type": "MOVE",
        "operands": [
            {
                "name": "A",
                "ref_mod_start": {"kind": "lit", "value": "1"},
                "ref_mod_length": {"kind": "lit", "value": "2"},
            },
            {"name": "A2"},
        ],
    }
    program = [("MAIN", [_move_literal("'ABC'", "A"), move, X_OUT])]

    assert (
        _ask(program, data, "X-OUT", [Condition("A", Op.NE, "'AAB'")], ("A",))
        == Answer.SAT
    )


def test_a_watched_name_that_is_not_one_field_is_refused() -> None:
    program = program_of(_asg([("MAIN", [X_OUT])], FIELDS))

    with pytest.raises(ValueError, match="^NOPE is not one field$"):
        lower(program, ("NOPE",))


def test_a_copy_from_a_variable_length_part_frees_the_target() -> None:
    """MOVE A(1:N) TO B: the start is known, the length is not, so the source is
    not A's whole extent and B is free."""
    data = (_x("A", "X(4)"), _x("N", "9"), _x("B", "X(3)"), *FIELDS)
    move = {
        "type": "MOVE",
        "operands": [
            {
                "name": "A",
                "ref_mod_start": {"kind": "lit", "value": "1"},
                "ref_mod_length": {"kind": "ref", "name": "N"},
            },
            {"name": "B"},
        ],
    }
    program = [("MAIN", [_move_literal("'WXYZ'", "A"), move, X_OUT])]

    assert (
        _ask(program, data, "X-OUT", [Condition("B", Op.EQ, "'W  '")], ("B",))
        == Answer.SAT
    )


def test_eibcalen_holds_one_value_for_the_whole_task() -> None:
    """CICS sets EIBCALEN when the task starts, and nothing in the program writes
    it, so two tests on it agree."""
    program = [
        ("MAIN", [_if(_ref("EIBCALEN"), "0", [], [_test("EIBCALEN", "0", [X_OUT])])])
    ]
    data = (*FIELDS, _x("Y-OUT"))
    inner = [("MAIN", [_test("EIBCALEN", "0", [_move("'y'", "Y-OUT")])])]

    assert _ask(program, FIELDS, "X-OUT") == Answer.UNSAT
    assert _ask(inner, data, "Y-OUT") == Answer.SAT


def test_a_number_compared_with_an_integer_reads_its_digits() -> None:
    """F PIC 9 with 88 F-ZERO VALUE 0 and 88 F-ONE VALUE 1. SET F-ONE TO TRUE
    writes the digit 1, so IF F-ZERO fails; a number moved from another number
    keeps its digit but not its zone, so a test against 1 may still go either
    way on its zone."""
    numeric = _x(
        "F",
        "9",
        conditions=[
            {"name": "F-ZERO", "values": [{"from": "0"}]},
            {"name": "F-ONE", "values": [{"from": "1"}]},
        ],
    )
    data = (numeric, _x("N", "9"), _x("G"), _x("X-OUT"))
    zero = [("MAIN", [_set_true("F-ONE"), _test("F", "0", [X_OUT])])]
    one = [("MAIN", [_set_true("F-ONE"), _test("F", "1", [X_OUT])])]
    moved = [
        (
            "MAIN",
            [_set_true("F-ONE"), _move("F", "N"), _if(_ref("N"), "1", [], [X_OUT])],
        )
    ]

    assert _ask(zero, data, "X-OUT") == Answer.UNSAT
    assert _ask(one, data, "X-OUT") == Answer.SAT
    assert _ask(moved, data, "X-OUT") == Answer.SAT


def test_two_numbers_that_test_equal_may_differ_in_their_zones() -> None:
    """IF N1 = N2 compares values: the digits must agree, the zones need not, so
    the test says nothing about the bytes."""
    data = (_x("N1", "9"), _x("N2", "9"), *FIELDS)
    same = {
        "type": "IF",
        "condition": {
            "not": False,
            "relation": {"left": _ref("N1"), "op": "==", "right": _ref("N2")},
        },
        "children": [X_OUT],
        "else_children": [],
    }
    program = [("MAIN", [same])]
    differ = Condition("N1", Op.NE, "N2")

    assert _ask(program, data, "X-OUT", [differ], ("N1", "N2")) == Answer.SAT


def test_an_inspect_frees_only_the_field_it_rewrites() -> None:
    """INSPECT G REPLACING ALL 'A' BY 'B' writes G and nothing else, so F keeps
    the value its test gave it and G may now hold anything."""
    inspect = {
        "type": "INSPECT",
        "inspect_type": "REPLACING",
        "source": {"name": "G"},
        "replacings": [
            {
                "mode": "ALL",
                "from": {"kind": "lit", "name": "'A'"},
                "to": {"kind": "lit", "name": "'B'"},
            }
        ],
    }
    program = [
        ("MAIN", [_move_literal("'A'", "G"), _test("F", "'Y'", [inspect, X_OUT])])
    ]

    assert _ask(program, FIELDS, "X-OUT", [_f(Op.EQ, "'N'")]) == Answer.UNSAT
    assert _ask(program, FIELDS, "X-OUT", [Condition("G", Op.EQ, "'A'")], ("G",)) == (
        Answer.SAT
    )


def test_an_integer_moved_into_a_number_sets_its_digits() -> None:
    """MOVE 1 TO N, N PIC 9(2), writes the digits 01, so IF N = 1 cannot fail and
    N's digits are 01. Into PIC 9V9 the literal's digits need a scale, which
    this encoding leaves unknown."""
    data = (_x("N", "9(2)"), _x("D", "9V9"), *FIELDS)
    into_n = [("MAIN", [_move_literal("1", "N"), _if(_ref("N"), "1", [], [X_OUT])])]
    held = [("MAIN", [_move_literal("1", "N"), _move_literal("1", "D"), X_OUT])]

    assert _ask(into_n, data, "X-OUT") == Answer.UNSAT
    assert _ask(
        held, data, "X-OUT", [Condition(Digits("N", 1, 2), Op.NE, "'01'")], ("N",)
    ) == (Answer.UNSAT)
    assert _ask(
        held, data, "X-OUT", [Condition(Digits("D", 1, 2), Op.NE, "'10'")], ("D",)
    ) == (Answer.SAT)


def test_a_test_on_a_field_not_tracked_can_go_either_way() -> None:
    """MOVE 'N' TO G, then IF G = 'Y': tracking G proves the THEN branch dead;
    tracking only F leaves the test unencoded, so both branches stay open, even
    when a question follows G's bytes."""
    program = [("MAIN", [_move_literal("'N'", "G"), _test("G", "'Y'", [X_OUT])])]

    assert (
        _ask(program, FIELDS, "X-OUT"),
        _ask(program, FIELDS, "X-OUT", kept=NamedFields(frozenset({"G"}))),
        _ask(program, FIELDS, "X-OUT", kept=NamedFields(frozenset({"F"}))),
        _ask(program, FIELDS, "X-OUT", [], ("G",), NamedFields(frozenset({"F"}))),
    ) == (Answer.UNSAT, Answer.UNSAT, Answer.SAT, Answer.SAT)


def test_tests_no_path_to_the_goal_runs_through_are_left_out() -> None:
    """MOVE 'N' TO G, IF G = 'Y' writes X-OUT, then IF F = 'Y' after it: asked
    about X-OUT, the test on G still proves it dead, while F, tested only where
    X-OUT can no longer be reached, leaves the state."""
    program = program_of(
        _asg(
            [
                (
                    "MAIN",
                    [
                        _move_literal("'N'", "G"),
                        _test("G", "'Y'", [X_OUT]),
                        _test("F", "'Y'", [_move_literal("'Z'", "G")]),
                    ],
                )
            ],
            FIELDS,
        )
    )
    node = next(node.id for node in program.cfg.nodes if "X-OUT" in node.writes)
    goal = Point("PROGA", node)
    whole, cut = lower(program), lower(program, kept=leading_to(program.cfg, node))

    assert (
        reaches(whole, goal, (), _clock()).answer,
        reaches(cut, goal, (), _clock()).answer,
        len(whole.storages["PROGA"].tracked("F")),
        len(cut.storages["PROGA"].tracked("F")),
        len(cut.storages["PROGA"].tracked("G")),
    ) == (Answer.UNSAT, Answer.UNSAT, 1, 0, 1)


def test_a_copy_of_eibcalen_bytes_takes_that_many_and_pads_with_spaces() -> None:
    """MOVE A(1:EIBCALEN) TO B, the way a program copies in its commarea: with
    EIBCALEN 2 and A 'WXYZ', B gets 'WX' padded to 'WX ', an alphanumeric MOVE
    from a shorter sender."""
    data = (_x("A", "X(4)"), _x("B", "X(3)"), *FIELDS)
    move = {
        "type": "MOVE",
        "operands": [
            {
                "name": "A",
                "ref_mod_start": {"kind": "lit", "value": "1"},
                "ref_mod_length": {"kind": "ref", "name": "EIBCALEN"},
            },
            {"name": "B"},
        ],
    }
    program = [
        ("MAIN", [_move_literal("'WXYZ'", "A"), _test("EIBCALEN", "2", [move, X_OUT])])
    ]

    assert (
        _ask(program, data, "X-OUT", [Condition("B", Op.NE, "'WX '")], ("B",)),
        _ask(program, data, "X-OUT", [Condition("B", Op.EQ, "'WX '")], ("B",)),
    ) == (Answer.UNSAT, Answer.SAT)


def test_a_perform_of_a_paragraph_that_ends_the_task_does_not_come_back() -> None:
    """PERFORM P, where P ends in STOP RUN or in an EXEC CICS XCTL with no handler:
    nothing after the PERFORM runs. A program with an ALTER keeps the CFG's edge
    past such a PERFORM, since its GO TOs may lead elsewhere."""
    xctl = {
        "type": "EXEC_CICS",
        "verb": "XCTL",
        "options": {"PROGRAM": {"text": "'OTHER'", "is_literal": True}},
    }
    ends = lambda last: [("MAIN", [_perform("P"), X_OUT, STOP]), ("P", [last])]
    altered = [("MAIN", [{"type": "ALTER"}, _perform("P"), X_OUT, STOP]), ("P", [STOP])]

    assert (
        _ask(ends(STOP), FIELDS, "X-OUT"),
        _ask(ends(xctl), FIELDS, "X-OUT"),
        _ask(altered, FIELDS, "X-OUT"),
    ) == (Answer.UNSAT, Answer.UNSAT, Answer.SAT)


def _writer(program: Program, field: str) -> str:
    return next(node.id for node in program.cfg.nodes if field in node.writes)


def test_an_outcome_mark_holds_the_last_outcome_of_its_test() -> None:
    program = program_of(_asg([("MAIN", [_test("F", "'Y'", [X_OUT])])], FIELDS))
    test = next(n.id for n in program.cfg.nodes if n.kind is NodeKind.TEST)
    system = lower(program, outcomes=(test,))
    point = Point("PROGA", _writer(program, "X-OUT"))

    def ask(outcome: Outcome) -> Answer:
        return reaches(system, point, (Took(test, outcome),), _clock()).answer

    assert (ask(Outcome.TRUE), ask(Outcome.FALSE), ask(Outcome.UNRUN)) == (
        Answer.SAT,
        Answer.UNSAT,
        Answer.UNSAT,
    )


def _first_perform(program: Program, node: str) -> str:
    if perform_edge(program.cfg, node):
        return node
    return _first_perform(program, program.cfg.successors(node)[0].target)


def _calls_by_branch(program: Program) -> tuple[str, str]:
    cfg = program.cfg
    test = next(
        n.id for n in cfg.nodes if n.kind is NodeKind.TEST and n.paragraph == "MAIN"
    )
    edges = {edge.kind: edge.target for edge in cfg.successors(test)}
    return (
        _first_perform(program, edges[EdgeKind.TRUE]),
        _first_perform(program, edges[EdgeKind.FALSE]),
    )


def test_an_entry_mark_names_the_call_site_that_entered_the_range() -> None:
    program = program_of(
        _asg(
            [
                (
                    "MAIN",
                    [_if(_ref("F"), "'Y'", [_perform("SUB")], [_perform("SUB")]), STOP],
                ),
                ("SUB", [_test("F", "'Y'", [X_OUT])]),
            ],
            FIELDS,
        )
    )
    then_call, else_call = _calls_by_branch(program)
    sub = performed(program.cfg, perform_edge(program.cfg, then_call)[0])
    system = lower(program, entries=(sub,))
    point = Point("PROGA", _writer(program, "X-OUT"))

    def ask(call: str) -> Answer:
        return reaches(system, point, (Entered(sub, call),), _clock()).answer

    assert (ask(then_call), ask(else_call)) == (Answer.SAT, Answer.UNSAT)
