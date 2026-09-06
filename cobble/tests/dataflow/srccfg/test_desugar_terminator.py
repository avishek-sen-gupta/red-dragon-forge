"""STOP RUN, GOBACK and EXIT PROGRAM: statements control does not leave.

The model is one subtraction -- a terminator lowers to the same node as any other
statement, minus its exit -- and everything in this file is a consequence of that,
because exits are what ``seq`` and ``build.py`` already sequence on.

Without it, fall-through paired every consecutive paragraph unconditionally, so
control cascaded off the entry paragraph's ``#end`` through every later paragraph in
declaration order. That made genuine dead code inexpressible: a paragraph nothing
performs and nothing runs into still collected guards from the cascade, so the
"unreachable" answer could essentially never be given about a real member.

Plain EXIT is the case that must NOT move. It is the no-op sentinel conventionally
written at the end of a PERFORM THRU range and it outnumbers the real terminators by
more than thirty to one in a CICS corpus, so treating it as one would cut most of a
program in half.
"""

from __future__ import annotations

import pytest

from cobble.dataflow.srccfg.build import build_program, end_id, label_id
from cobble.dataflow.srccfg.cfg import EdgeKind
from cobble.dataflow.srccfg.dataflow import guards_of, reaching_conditions
from cobble.dataflow.srccfg.query import guards_report

TERMINATORS = ("STOP_RUN", "GOBACK", "EXIT_PROGRAM")


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _rel(left: str, right: str) -> dict:
    return {
        "not": False,
        "relation": {
            "left": {"kind": "ref", "name": left},
            "op": "==",
            "right": {"kind": "lit", "value": right},
        },
    }


def _perform(target: str) -> dict:
    return {"type": "PERFORM", "operands": [target]}


def _two_paragraphs(first_statements: list) -> dict:
    return {
        "program_id": "PROGA",
        "paragraphs": [
            {"name": "1000-FIRST", "statements": first_statements},
            {"name": "2000-SECOND", "statements": [_move("'S'", "WS-SECOND")]},
        ],
    }


def _writer_of(cfg, field: str) -> str:
    return next(node.id for node in cfg.nodes if field in node.writes)


@pytest.mark.parametrize("terminator", TERMINATORS)
def test_a_terminator_has_no_successor(program_of, terminator: str) -> None:
    cfg = build_program(program_of([{"type": terminator}, _move("'A'", "WS-AFTER")]))

    assert cfg.successors("MAIN/0") == ()


@pytest.mark.parametrize("terminator", TERMINATORS)
def test_the_statement_after_a_terminator_is_reached_by_nothing(
    program_of, terminator: str
) -> None:
    """The node is still built. It is the same paragraph's second statement whether
    or not the first one stops, and dropping it would renumber every id after it."""
    cfg = build_program(program_of([{"type": terminator}, _move("'A'", "WS-AFTER")]))

    assert cfg.predecessors("MAIN/1") == ()
    assert guards_of(reaching_conditions(cfg), "MAIN/1") == ()


@pytest.mark.parametrize("terminator", TERMINATORS)
def test_a_paragraph_ending_in_a_terminator_does_not_reach_its_own_end(
    program_of, terminator: str
) -> None:
    """``#end`` is where both the fall-through to the next paragraph and the RETURN
    of every PERFORM of this paragraph hang, which is why one severed route here
    settles both of them."""
    cfg = build_program(program_of([{"type": terminator}]))

    assert cfg.predecessors(end_id("MAIN")) == ()


@pytest.mark.parametrize("terminator", TERMINATORS)
def test_a_paragraph_after_one_that_stops_is_not_reached(
    asg_of, terminator: str
) -> None:
    cfg = build_program(
        asg_of(_two_paragraphs([_move("'F'", "WS-A"), {"type": terminator}]))
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, label_id("2000-SECOND")) == ()
    assert guards_of(reaching, _writer_of(cfg, "WS-SECOND")) == ()


def test_an_unreached_paragraph_is_reported_unreachable_and_not_abandoned(
    asg_of,
) -> None:
    """The distinction the cascade used to make impossible. No guards means one of
    two very different things, and only a node the walk did not ABANDON may be
    reported as code the program cannot reach."""
    cfg = build_program(asg_of(_two_paragraphs([{"type": "GOBACK"}])))
    second = _writer_of(cfg, "WS-SECOND")

    assert second not in reaching_conditions(cfg).abandoned
    assert any("unreachable from PROGA" in line for line in guards_report(cfg, second))


def test_a_terminator_in_one_arm_leaves_the_other_arm_falling_through(asg_of) -> None:
    """A terminator contributes no exit; the arm beside it still contributes its own.
    So the next paragraph keeps exactly the guard of the path that did not stop."""
    cfg = build_program(
        asg_of(
            _two_paragraphs(
                [
                    {
                        "type": "IF",
                        "condition": _rel("WS-FLAG", "'Y'"),
                        "children": [{"type": "GOBACK"}],
                        "else_children": [_move("'E'", "WS-ELSE")],
                    }
                ]
            )
        )
    )

    guards = guards_of(reaching_conditions(cfg), _writer_of(cfg, "WS-SECOND"))

    assert [[kind.value for _, kind in guard] for guard in guards] == [
        [EdgeKind.FALSE.value]
    ]


def test_plain_exit_still_falls_through(asg_of) -> None:
    """The regression this whole model has to avoid. EXIT is a no-op sentinel, not a
    terminator, and it ends a large fraction of the paragraphs in a real member."""
    cfg = build_program(
        asg_of(_two_paragraphs([_move("'F'", "WS-A"), {"type": "EXIT"}]))
    )

    assert [(e.target, e.kind) for e in cfg.successors(end_id("1000-FIRST"))] == [
        (label_id("2000-SECOND"), EdgeKind.FALLTHRU)
    ]
    assert guards_of(reaching_conditions(cfg), _writer_of(cfg, "WS-SECOND")) == ((),)


def test_performing_a_paragraph_that_stops_still_reaches_the_next_statement(
    asg_of,
) -> None:
    """The one imprecision kept on purpose, and the safe direction to keep it in.

    A PERFORM of a paragraph ending in GOBACK never comes back, so the statement
    after the PERFORM is genuinely dead. Refusing that FLOW edge would be the precise
    answer -- and the walk refuses a call's FLOW edge only when it predicts a RETURN
    will arrive instead, which here it cannot, since nothing reaches the paragraph's
    ``#end`` for the RETURN to leave from. So the FLOW is the only route onward and it
    stays open, over-approximating in the same direction ``link.py`` chose for XCTL.
    """
    cfg = build_program(
        asg_of(
            {
                "program_id": "PROGA",
                "paragraphs": [
                    {
                        "name": "MAIN",
                        "statements": [_perform("HANDLER"), _move("'A'", "WS-AFTER")],
                    },
                    {"name": "HANDLER", "statements": [{"type": "GOBACK"}]},
                ],
            }
        )
    )

    assert cfg.predecessors(end_id("HANDLER")) == ()
    assert guards_of(reaching_conditions(cfg), _writer_of(cfg, "WS-AFTER")) == ((),)
