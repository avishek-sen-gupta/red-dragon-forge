import json
from collections.abc import Callable, Iterator, Mapping, Sequence

from cics.statements import ExecCicsStatement
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


def _program(
    name: str = "PROGA",
    data: Sequence[Statement] = DATA,
    linkage: Sequence[Statement] = LINKAGE,
    body: Sequence[Statement] = BODY,
) -> Program:
    asg = {
        "program_id": name,
        "data_fields": list(data),
        "linkage_fields": list(linkage),
        "paragraphs": [{"name": "MAIN", "statements": list(body)}],
    }
    with cached_asg_dialect_parsers_registered():
        return program_of(CobolASG.from_dict(json.loads(json.dumps(asg))))


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


def test_a_dynamic_xctl_reaches_only_the_program_its_field_names() -> None:
    """PROGX moves 'PROGA' into WS-PGM and XCTLs to PROGRAM(WS-PGM). The links
    list PROGA and PROGB for that XCTL, but only PROGA is handed the commarea,
    so only PROGA's task can find EIBCALEN other than 0."""
    xctl = {
        "type": "EXEC_CICS",
        "verb": "XCTL",
        "options": {
            "PROGRAM": {"text": "WS-PGM", "is_literal": False},
            "COMMAREA": {"text": "WS-COMM", "is_literal": False},
        },
    }
    caller = _program(
        "PROGX",
        (_x("WS-PGM", "X(5)"), _x("WS-COMM")),
        (),
        [_move("'PROGA'", "WS-PGM"), xctl],
    )
    callees = (_program("PROGA"), _program("PROGB"))
    node = next(
        n for n, s in caller.statements.items() if isinstance(s, ExecCicsStatement)
    )
    links = tuple(
        LinkRow(
            caller="PROGX",
            node=node,
            transfer="XCTL",
            callee=callee.cfg.program,
            caller_extent=_extent(caller, "WS-COMM"),
            callee_extent=_extent(callee, "LK-STATE"),
            returns=False,
            reason="",
        )
        for callee in callees
    )
    system = converse((caller, *callees), links)

    def handed(program: Program) -> Answer:
        test = next(n.id for n in program.cfg.nodes if n.atom.left == "EIBCALEN")
        (taken,) = (e for e in program.cfg.successors(test) if e.kind.name == "FALSE")
        point = Point(program.cfg.program, taken.target)
        return reaches(system, point, (), _clock()).answer

    assert tuple(handed(p) for p in callees) == (Answer.SAT, Answer.UNSAT)


def test_an_xctl_to_a_program_of_the_conversation_finds_it_installed() -> None:
    """PROGX arms HANDLE CONDITION PGMIDERR(MISSING) and XCTLs to the program
    WS-PGM names. Naming PROGA, one of the programs, never raises PGMIDERR, so
    MISSING never runs; naming NOPE, which is not one of them, may."""
    handle = {
        "type": "EXEC_CICS",
        "verb": "HANDLE CONDITION",
        "options": {"PGMIDERR": {"text": "MISSING", "is_literal": False}},
    }
    xctl = {
        "type": "EXEC_CICS",
        "verb": "XCTL",
        "options": {
            "PROGRAM": {"text": "WS-PGM", "is_literal": False},
            "COMMAREA": {"text": "WS-COMM", "is_literal": False},
        },
    }

    def missing(target: str) -> Answer:
        caller = _paragraphs(
            "PROGX",
            (_x("WS-PGM", "X(5)"), _x("WS-COMM"), _x("X-OUT")),
            [
                ("MAIN", [handle, _move(f"'{target}'", "WS-PGM"), xctl]),
                ("MISSING", [_move("'x'", "X-OUT"), STOP]),
            ],
        )
        callee = _program("PROGA")
        node = next(
            n
            for n, s in caller.statements.items()
            if isinstance(s, ExecCicsStatement) and s.verb == "XCTL"
        )
        link = LinkRow(
            caller="PROGX",
            node=node,
            transfer="XCTL",
            callee="PROGA",
            caller_extent=_extent(caller, "WS-COMM"),
            callee_extent=_extent(callee, "LK-STATE"),
            returns=False,
            reason="",
        )
        system = converse((caller, callee), (link,))
        point = Point("PROGX", _writer(caller, "X-OUT"))
        return reaches(system, point, (), _clock()).answer

    assert (missing("PROGA"), missing("NOPE")) == (Answer.UNSAT, Answer.SAT)


def _paragraphs(
    name: str,
    data: Sequence[Statement],
    paragraphs: Sequence[tuple[str, Sequence[Statement]]],
) -> Program:
    asg = {
        "program_id": name,
        "data_fields": list(data),
        "linkage_fields": [],
        "paragraphs": [{"name": p, "statements": list(s)} for p, s in paragraphs],
    }
    with cached_asg_dialect_parsers_registered():
        return program_of(CobolASG.from_dict(json.loads(json.dumps(asg))))


def test_return_and_send_map_never_raise_pgmiderr() -> None:
    """IBM lists no PGMIDERR among the conditions of RETURN or SEND MAP, so a
    handler armed for PGMIDERR alone is not entered from either; an XCTL that
    names its target by literal still may."""
    handle = {
        "type": "EXEC_CICS",
        "verb": "HANDLE CONDITION",
        "options": {"PGMIDERR": {"text": "MISSING", "is_literal": False}},
    }

    def command(verb: str, options: Mapping[str, object]) -> Answer:
        program = _paragraphs(
            "PROGX",
            (_x("X-OUT"),),
            [
                (
                    "MAIN",
                    [
                        handle,
                        {"type": "EXEC_CICS", "verb": verb, "options": options},
                        STOP,
                    ],
                ),
                ("MISSING", [_move("'x'", "X-OUT"), STOP]),
            ],
        )
        point = Point("PROGX", _writer(program, "X-OUT"))
        return reaches(lower(program), point, (), _clock()).answer

    assert (
        command("RETURN", {}),
        command("SEND MAP", {"MAP": {"text": "'M'", "is_literal": True}}),
        command("XCTL", {"PROGRAM": {"text": "'NOPE'", "is_literal": True}}),
    ) == (Answer.UNSAT, Answer.UNSAT, Answer.SAT)
