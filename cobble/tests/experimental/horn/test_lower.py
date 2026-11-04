import json
from collections.abc import Callable, Iterator, Mapping, Sequence

import pytest
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.extent_line import ExtentLine
from cobble.experimental.horn.answer import Answer
from cobble.experimental.horn.condition import Condition, Op
from cobble.experimental.horn.lower import lower
from cobble.experimental.horn.point import Point
from cobble.experimental.horn.program import program_of
from cobble.experimental.horn.reaches import reaches
from cobol_asg.asg_types import CobolASG

Statement = Mapping[str, object]


def _clock() -> Callable[[], float]:
    ticks: Iterator[float] = iter(float(n) for n in range(1000))
    return lambda: next(ticks)


def _asg(paragraphs: Sequence[tuple[str, Sequence[Statement]]]) -> CobolASG:
    body = {
        "program_id": "PROGA",
        "paragraphs": [
            {"name": name, "statements": list(statements)}
            for name, statements in paragraphs
        ],
    }
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(json.loads(json.dumps(body)))


def _field(name: str, start: int, length: int, pic: str = "X") -> ExtentLine:
    return _declared(name, ((start, length),), pic)


def _declared(
    name: str, places: Sequence[tuple[int, int]], pic: str = "X"
) -> ExtentLine:
    return ExtentLine(
        id=f"PROGA.{name}",
        program="PROGA",
        extents=tuple(
            f"{name}@working_storage[{start}:{start + length}]"
            for start, length in places
        ),
        names=tuple(name for _ in places),
        records=tuple(name for _ in places),
        paths=tuple((name,) for _ in places),
        levels=tuple(1 for _ in places),
        pics=tuple(pic for _ in places),
        usages=tuple("DISPLAY" for _ in places),
        occurs=tuple(0 for _ in places),
        origins=tuple("WORKING-STORAGE" for _ in places),
        values=tuple("" for _ in places),
        redefines=tuple("" for _ in places),
    )


def _move(value: str, target: str) -> Statement:
    return {"type": "MOVE", "operands": [{"name": value}, {"name": target}]}


def _if(
    left: str, right: str, then: Sequence[Statement], otherwise: Sequence[Statement]
) -> Statement:
    return {
        "type": "IF",
        "condition": {
            "not": False,
            "relation": {
                "left": {"kind": "ref", "name": left},
                "op": "==",
                "right": {"kind": "lit", "value": right},
            },
        },
        "children": list(then),
        "else_children": list(otherwise),
    }


def _perform(target: str, thru: str = "") -> Statement:
    return {"type": "PERFORM", "operands": [target], **({"thru": thru} if thru else {})}


def _goto(target: str) -> Statement:
    return {"type": "GOTO", "form": "simple", "target": {"paragraph": target}}


STOP: Statement = {"type": "STOP_RUN"}

FIELDS = (_field("F", 0, 1), _field("G", 1, 1))


def _ask(
    paragraphs: Sequence[tuple[str, Sequence[Statement]]],
    extents: Sequence[ExtentLine],
    writer: str,
    conditions: Sequence[Condition] = (),
) -> Answer:
    asg = _asg(paragraphs)
    program = program_of(asg, extents)
    node = next(node.id for node in program.cfg.nodes if writer in node.writes)
    return reaches(lower(program), Point("PROGA", node), conditions, _clock()).answer


def _f(op: Op, value: str) -> Condition:
    return Condition("F", op, value)


def test_a_test_constrains_the_values_after_it() -> None:
    program = [("MAIN", [_if("F", "'Y'", [_move("'x'", "X-OUT")], [])])]

    assert (
        _ask(program, FIELDS, "X-OUT", [_f(Op.EQ, "'N'")]),
        _ask(program, FIELDS, "X-OUT", [_f(Op.EQ, "'Y'")]),
        _ask(program, FIELDS, "X-OUT", [_f(Op.NE, "'Y'")]),
    ) == (Answer.UNSAT, Answer.SAT, Answer.UNSAT)


def test_contradictory_tests_make_a_point_unreachable() -> None:
    inner = _if("F", "'Y'", [_move("'x'", "X-OUT")], [])
    program = [("MAIN", [_if("F", "'N'", [inner], [])])]

    assert _ask(program, FIELDS, "X-OUT") == Answer.UNSAT


def test_a_write_frees_the_field_it_overlaps() -> None:
    then = [_move("G", "F"), _move("'x'", "X-OUT")]
    program = [("MAIN", [_if("F", "'Y'", then, [])])]

    assert _ask(program, FIELDS, "X-OUT", [_f(Op.EQ, "'N'")]) == Answer.SAT


def test_a_group_write_frees_the_flags_inside_it() -> None:
    extents = (_field("REC", 0, 2, pic=""), *FIELDS)
    then = [_move("G", "REC"), _move("'x'", "X-OUT")]
    program = [("MAIN", [_if("F", "'Y'", then, [])])]

    assert _ask(program, extents, "X-OUT", [_f(Op.EQ, "'N'")]) == Answer.SAT


def test_a_perform_returns_only_to_its_own_caller() -> None:
    program = [
        (
            "MAIN",
            [
                _if("F", "'Y'", [_perform("P"), _move("'a'", "A-OUT")], []),
                _if("F", "'N'", [_perform("P"), _move("'b'", "B-OUT")], []),
                STOP,
            ],
        ),
        ("P", [_if("F", "'Y'", [_move("'p'", "P-OUT")], [])]),
    ]

    assert (
        _ask(program, FIELDS, "B-OUT", [_f(Op.EQ, "'Y'")]),
        _ask(program, FIELDS, "B-OUT", [_f(Op.EQ, "'N'")]),
        _ask(program, FIELDS, "A-OUT", [_f(Op.EQ, "'Y'")]),
    ) == (Answer.UNSAT, Answer.SAT, Answer.SAT)


def test_a_thru_range_falls_through_inside_and_stops_at_its_end() -> None:
    program = [
        ("MAIN", [_perform("A", thru="B"), _move("'r'", "R-OUT"), STOP]),
        ("A", [_move("'a'", "A-OUT")]),
        ("B", [_move("'b'", "B-OUT")]),
        ("C", [_move("'c'", "C-OUT")]),
    ]

    assert (
        _ask(program, FIELDS, "B-OUT"),
        _ask(program, FIELDS, "R-OUT"),
        _ask(program, FIELDS, "C-OUT"),
    ) == (Answer.SAT, Answer.SAT, Answer.UNSAT)


def test_a_name_declared_twice_is_not_tracked() -> None:
    extents = (_declared("D", ((0, 1), (5, 1))), *FIELDS)
    inner = _if("D", "'Y'", [_move("'x'", "X-OUT")], [])
    program = [("MAIN", [_if("D", "'N'", [inner], [])])]

    assert _ask(program, extents, "X-OUT") == Answer.SAT
    with pytest.raises(ValueError, match="^D is not a tracked field$"):
        _ask(program, extents, "X-OUT", [Condition("D", Op.EQ, "'Y'")])


def test_a_goto_out_of_a_range_does_not_return_to_the_perform() -> None:
    program = [
        ("MAIN", [_perform("P"), _move("'r'", "R-OUT"), STOP]),
        ("P", [_if("F", "'Y'", [_goto("Q")], [])]),
        ("Q", [_move("'q'", "Q-OUT")]),
    ]

    assert (
        _ask(program, FIELDS, "Q-OUT", [_f(Op.EQ, "'Y'")]),
        _ask(program, FIELDS, "R-OUT", [_f(Op.EQ, "'Y'")]),
        _ask(program, FIELDS, "R-OUT", [_f(Op.EQ, "'N'")]),
    ) == (Answer.SAT, Answer.UNSAT, Answer.SAT)
