import json
from collections.abc import Callable, Iterator, Mapping, Sequence

from cobble.dataflow.combine.link_row import LinkRow
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.experimental.horn.answer import Answer
from cobble.experimental.horn.condition import Condition, Op, Visited
from cobble.experimental.horn.conversation import converse
from cobble.experimental.horn.lower import HornSystem, lower
from cobble.experimental.horn.point import Point
from cobble.experimental.horn.program import Program, program_of
from cobble.experimental.horn.reaches import reaches
from cobol_asg.asg_types import CobolASG

Statement = Mapping[str, object]


def _clock() -> Callable[[], float]:
    ticks: Iterator[float] = iter(float(n) for n in range(1000))
    return lambda: next(ticks)


def _x(name: str, pic: str = "X", **extra: object) -> Statement:
    return {"name": name, "level": 1, "pic": pic, **extra}


def _ref(name: str) -> Mapping[str, object]:
    return {"kind": "ref", "name": name}


def _if(
    left: str, right: str, then: Sequence[Statement], otherwise: Sequence[Statement]
) -> Statement:
    return {
        "type": "IF",
        "condition": {
            "not": False,
            "relation": {
                "left": _ref(left),
                "op": "==",
                "right": {"kind": "lit", "value": right},
            },
        },
        "children": list(then),
        "else_children": list(otherwise),
    }


def _move(value: str, target: str) -> Statement:
    return {"type": "MOVE", "operands": [{"name": value}, {"name": target}]}


STOP: Statement = {"type": "STOP_RUN"}

DATA = (
    _x("WS-STATE"),
    _x("WS-COMM"),
    _x("OK-FLAG"),
    _x("WS-V", value="V"),
    _x("X-OUT"),
    _x("Y-OUT"),
)
LINKAGE = (_x("LK-STATE"),)

BODY = [
    _if("EIBCALEN", "0", [_move("'I'", "WS-STATE")], [_move("LK-STATE", "WS-STATE")]),
    _if("WS-V", "'V'", [], [_move("'y'", "Y-OUT")]),
    _if("WS-STATE", "'C'", [_move("'x'", "X-OUT")], []),
    _if("WS-STATE", "'I'", [_move("'C'", "OK-FLAG"), _move("OK-FLAG", "WS-STATE")], []),
    _move("WS-STATE", "WS-COMM"),
    STOP,
]


def _program() -> Program:
    body = {
        "program_id": "PROGA",
        "data_fields": list(DATA),
        "linkage_fields": list(LINKAGE),
        "paragraphs": [{"name": "MAIN", "statements": BODY}],
    }
    with cached_asg_dialect_parsers_registered():
        return program_of(CobolASG.from_dict(json.loads(json.dumps(body))))


def _writer(program: Program, name: str) -> str:
    return next(node.id for node in program.cfg.nodes if name in node.writes)


def _extent(program: Program, name: str) -> str:
    (cell,) = program.index.cells_named(name, (), 0)
    return str(program.index.extent_of(cell))


def _link(program: Program, caller: str, transfer: str) -> LinkRow:
    """``caller``'s task ends at STOP RUN, the node after the move into WS-COMM,
    handing WS-COMM over as LK-STATE."""
    (step,) = program.cfg.successors(_writer(program, "WS-COMM"))
    return LinkRow(
        caller=caller,
        node=step.target,
        transfer=transfer,
        callee="PROGA",
        caller_extent=_extent(program, "WS-COMM"),
        callee_extent=_extent(program, "LK-STATE"),
        returns=False,
        reason="",
    )


def _ask(
    system: HornSystem,
    program: Program,
    writer: str,
    conditions: Sequence[Condition | Visited] = (),
) -> Answer:
    point = Point("PROGA", _writer(program, writer))
    return reaches(system, point, conditions, _clock()).answer


def test_a_conversation_carries_the_commarea_from_one_task_to_the_next() -> None:
    """The first task starts with no commarea, sets 'I', passes the check that
    sets 'C', and hands 'C' on; only a later task, entered with 'C', reaches
    X-OUT. Taken alone, a task may be entered with 'C' and no check behind it."""
    program = _program()
    checked = Point("PROGA", _writer(program, "OK-FLAG"))
    links = (_link(program, "PROGA", "RETURN_TRANSID"),)
    conversation = converse((program,), links, marks=(checked,))
    task = lower(program, marks=(checked,))

    assert _ask(conversation, program, "X-OUT") == Answer.SAT
    assert _ask(conversation, program, "X-OUT", [Visited(checked, True)]) == (
        Answer.SAT
    )
    assert _ask(conversation, program, "X-OUT", [Visited(checked, False)]) == (
        Answer.UNSAT
    )
    assert _ask(task, program, "X-OUT", [Visited(checked, False)]) == Answer.SAT


def test_each_task_starts_from_its_value_clauses() -> None:
    """WS-V VALUE 'V' and nothing writes it, so every task finds 'V' there."""
    program = _program()
    links = (_link(program, "PROGA", "RETURN_TRANSID"),)

    assert _ask(converse((program,), links), program, "Y-OUT") == Answer.UNSAT
    assert _ask(lower(program), program, "Y-OUT") == Answer.SAT


def test_a_transfer_from_outside_the_conversation_brings_any_commarea() -> None:
    """OTHER is not one of the programs, so what it hands over is unknown, and it
    may be 'C' with no check behind it."""
    program = _program()
    checked = Point("PROGA", _writer(program, "OK-FLAG"))
    links = (
        _link(program, "PROGA", "RETURN_TRANSID"),
        _link(program, "OTHER", "XCTL"),
    )
    conversation = converse((program,), links, marks=(checked,))

    assert _ask(conversation, program, "X-OUT", [Visited(checked, False)]) == (
        Answer.SAT
    )
