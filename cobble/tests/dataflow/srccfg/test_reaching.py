"""A node's reaching conditions are the guards along the paths that reach it.

The measured failure this replaces was a guard stack: it negated a two-clause AND as
NOT A AND NOT B, so the ELSE arm of the commonest COBOL shape got a condition no
input satisfies. Here negation is an edge polarity, so the same shape comes out as
two paths -- which is what NOT (A AND B) means.
"""

from __future__ import annotations

from cobble.dataflow.srccfg.build import (
    build_program,
    end_id,
    label_id,
)
from cobble.dataflow.srccfg.cfg import Atom, Cfg, Edge, EdgeKind, Node, NodeKind
from cobble.dataflow.srccfg.dataflow import (
    MAX_PATHS,
    Reaching,
    entry_of,
    guard_set,
    guard_text,
    guards_of,
    reaching_conditions,
)
from cobble.dataflow.srccfg.synthetic import IMPLICIT_FIRST


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


def _and(left: dict, right: dict) -> dict:
    return {"op": "AND", "left": left, "right": right}


def _if(condition: dict, then: list[dict], otherwise: list[dict] | tuple = ()) -> dict:
    return {
        "type": "IF",
        "condition": condition,
        "children": list(then),
        "else_children": list(otherwise),
    }


def _perform(target: str) -> dict:
    return {"type": "PERFORM", "operands": [target]}


def _goto(target: str) -> dict:
    return {"type": "GOTO", "form": "simple", "target": {"paragraph": target}}


def _program(*paragraphs: dict) -> dict:
    return {"program_id": "PROGA", "paragraphs": list(paragraphs)}


def _writer_of(cfg: Cfg, field: str) -> str:
    return next(node.id for node in cfg.nodes if field in node.writes)


def _kinds(guard) -> list[EdgeKind]:
    return [kind for _, kind in guard]


def _kinds_of_each(reaching: Reaching, node_id: str) -> list[list[str]]:
    return sorted(
        [kind.value for kind in _kinds(guard)] for guard in guards_of(reaching, node_id)
    )


def test_an_unguarded_assignment_has_one_empty_guard(program_of) -> None:
    """65% of a corpus's assignments carry a guard, which means 35% do not -- and an
    empty tuple of paths would say "unreachable", the opposite claim."""
    cfg = build_program(program_of([_move("'A'", "WS-FLAG-A")]))

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-FLAG-A")) == ((),)


def test_an_assignment_in_a_then_arm_carries_the_true_polarity(program_of) -> None:
    cfg = build_program(
        program_of([_if(_rel("WS-FLAG-A", "'Y'"), [_move("'A'", "WS-RESULT")])])
    )

    reaching = reaching_conditions(cfg)
    (guard,) = guards_of(reaching, _writer_of(cfg, "WS-RESULT"))

    assert _kinds(guard) == [EdgeKind.TRUE]


def test_the_else_arm_of_a_two_clause_and_is_reached_by_two_paths(program_of) -> None:
    """The whole point. NOT (A AND B) is NOT A OR NOT B, and an OR is two paths --
    so this node has two guards, each ending in a single FALSE, not one guard whose
    two clauses are both negated.
    """
    cfg = build_program(
        program_of(
            [
                _if(
                    _and(_rel("WS-FLAG-A", "'Y'"), _rel("WS-FLAG-B", "'Y'")),
                    [_move("'A'", "WS-TAKEN")],
                    [_move("'B'", "WS-SKIPPED")],
                )
            ]
        )
    )

    reaching = reaching_conditions(cfg)
    guards = guards_of(reaching, _writer_of(cfg, "WS-SKIPPED"))

    assert sorted(len(guard) for guard in guards) == [1, 2]
    assert all(guard[-1][1] == EdgeKind.FALSE for guard in guards)


def test_the_then_arm_of_a_two_clause_and_is_one_path_of_two_tests(program_of) -> None:
    cfg = build_program(
        program_of(
            [
                _if(
                    _and(_rel("WS-FLAG-A", "'Y'"), _rel("WS-FLAG-B", "'Y'")),
                    [_move("'A'", "WS-TAKEN")],
                )
            ]
        )
    )

    reaching = reaching_conditions(cfg)
    (guard,) = guards_of(reaching, _writer_of(cfg, "WS-TAKEN"))

    assert _kinds(guard) == [EdgeKind.TRUE, EdgeKind.TRUE]


def test_a_statement_after_the_if_is_reached_under_every_arm(program_of) -> None:
    """A node reached under both polarities of one test is unconditional in effect.
    Both paths have to be there for a later pass to see that.
    """
    cfg = build_program(
        program_of(
            [
                _if(_rel("WS-FLAG-A", "'Y'"), [_move("'A'", "WS-X")]),
                _move("'B'", "WS-AFTER"),
            ]
        )
    )

    reaching = reaching_conditions(cfg)
    guards = guards_of(reaching, _writer_of(cfg, "WS-AFTER"))

    assert len(guards) == 2
    assert sorted(_kinds(guard)[0].value for guard in guards) == ["FALSE", "TRUE"]


def test_a_performed_paragraph_carries_the_guard_of_the_call_site(asg_of) -> None:
    """This is why a per-paragraph analysis is not enough: the assignment is
    unconditional where it is written and conditional in every run."""
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [_if(_rel("WS-FLAG-A", "'Y'"), [_perform("SET-IT")])],
                },
                {"name": "SET-IT", "statements": [_move("'A'", "WS-RESULT")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)
    guards = guards_of(reaching, _writer_of(cfg, "WS-RESULT"))

    assert any(EdgeKind.TRUE in guard_kinds for guard_kinds in map(_kinds, guards))


def test_a_return_edge_is_only_taken_back_to_its_own_call_site(asg_of) -> None:
    """A paragraph PERFORMed twice has two return edges. Following the wrong one
    joins the guard of call site A to everything after call site B, and on a corpus
    where a paragraph is performed from a dozen places that is where the guard sets
    stop meaning anything.
    """
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [
                        _if(
                            _rel("WS-FLAG-A", "'Y'"),
                            [_perform("SET-IT"), _move("'1'", "WS-AFTER-A")],
                            [_perform("SET-IT"), _move("'2'", "WS-AFTER-B")],
                        )
                    ],
                },
                {"name": "SET-IT", "statements": [_move("'A'", "WS-RESULT")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert [
        _kinds(guard) for guard in guards_of(reaching, _writer_of(cfg, "WS-AFTER-A"))
    ] == [[EdgeKind.TRUE]]
    assert [
        _kinds(guard) for guard in guards_of(reaching, _writer_of(cfg, "WS-AFTER-B"))
    ] == [[EdgeKind.FALSE]]


def test_the_statement_after_a_perform_is_reached_once_not_twice(asg_of) -> None:
    """A CALL node keeps a FLOW edge to the next statement as well as the PERFORM
    edge, and the paragraph's RETURN edge lands on that same FLOW target. Walking
    both would report the continuation twice under one guard, and a paragraph with
    ten PERFORMs would report 2^10 duplicates -- so control goes through the
    paragraph and comes back, and the FLOW edge is only the fallback.
    """
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [
                        _perform("SET-IT"),
                        _perform("SET-IT-TOO"),
                        _move("'A'", "WS-AFTER"),
                    ],
                },
                {"name": "SET-IT", "statements": [_move("'B'", "WS-B")]},
                {"name": "SET-IT-TOO", "statements": [_move("'C'", "WS-C")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-AFTER")) == ((),)


def test_a_performed_paragraph_does_not_fall_through_to_the_next_one(asg_of) -> None:
    """PERFORM MIDDLE returns at the end of MIDDLE. Following the fall-through edge
    out of it as well would run TAIL under the caller's guard, and on a driver
    paragraph that performs forty others those invented paths fill the path cap and
    evict the returns the driver's own later statements are reachable only by --
    measured as 39 nodes with no guards at all on a 922-node synthetic program.

    TAIL is reached all the same, by the other route: control runs off MAIN's end into
    MIDDLE and on into TAIL, unconditionally, because the builder models no STOP RUN.
    Both routes into MIDDLE carry the empty guard, and a guard is a condition -- so it
    is recorded once. What is under test is that TAIL is reached WITHOUT the PERFORM
    lending it a frame: the caller's guard never travels down the fall-through.
    """
    cfg = build_program(
        asg_of(
            _program(
                {"name": "MAIN", "statements": [_perform("MIDDLE")]},
                {"name": "MIDDLE", "statements": [_move("'A'", "WS-MIDDLE")]},
                {"name": "TAIL", "statements": [_move("'B'", "WS-TAIL")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-MIDDLE")) == ((),)
    assert guards_of(reaching, _writer_of(cfg, "WS-TAIL")) == ((),)
    assert reaching.abandoned == frozenset()


def test_a_perform_thru_still_falls_through_inside_the_range(asg_of) -> None:
    """The other side of that rule: a paragraph in the middle of a THRU range
    reaches the next one by falling through, and the return comes from the range's
    last paragraph. Refusing fall-through inside a frame outright would report the
    whole tail of every range unreachable."""
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [
                        {"type": "PERFORM", "operands": ["FIRST"], "thru": "LAST"},
                        _move("'Z'", "WS-AFTER"),
                    ],
                },
                {"name": "FIRST", "statements": [_move("'A'", "WS-FIRST")]},
                {"name": "LAST", "statements": [_move("'B'", "WS-LAST")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-FIRST")) == ((),)
    assert guards_of(reaching, _writer_of(cfg, "WS-LAST")) == ((),)
    assert guards_of(reaching, _writer_of(cfg, "WS-AFTER")) == ((),)


def test_a_call_whose_return_is_spent_still_reaches_the_next_statement(asg_of) -> None:
    """One paragraph's end carrying two calls' return edges, with the overlap at the
    range's LAST paragraph.

    PB is performed on its own and is also where the second call's THRU range ends, so
    PB#end has a RETURN edge for each of them. The first call spends its own getting back
    to the second call. The second call then enters PA, falls through into PB -- a second
    activation of a paragraph this path has already walked -- and returns from PB#end to
    the statement after itself, not back to the call site it already left.

    Two rules have to hold together for that. Frames make the second activation possible,
    and matching returns to their own frame is what sends this one to MAIN/2 rather than
    MAIN/1. Get either wrong and the walk either dies at the second call or loops back
    through it; both report the tail of the program as unreachable, which is the worst
    answer this pass can give.
    """
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [
                        _perform("PB"),
                        {"type": "PERFORM", "operands": ["PA"], "thru": "PB"},
                        _move("'Z'", "WS-AFTER"),
                    ],
                },
                {"name": "PA", "statements": [_move("'A'", "WS-A")]},
                {"name": "PB", "statements": [_move("'B'", "WS-B")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-AFTER")) == ((),)


def test_a_call_whose_return_never_fires_does_not_zero_the_rest_of_the_program(
    asg_of,
) -> None:
    """The shape that cost a real member 82% of its guards, at its smallest.

    PB is performed on its own and lies STRICTLY INSIDE the later PERFORM of PA THRU PC --
    not its start, not its end. So the second call's return leaves from PC#end, and the
    only route there runs PA, PB, PC in order. While ``seen`` was scoped to the whole path
    rather than to the activation, PB was already on it: the fall-through into PB was
    barred, PC was never reached, no return fired, and the FLOW edge past the second call
    had been refused on the prediction that one would. Every statement after the call read
    as unreachable -- measured at 94% of a synthetic program's nodes.

    The three statements after the call stand in for that tail. What is under test is that
    the second activation of PB runs, so the range completes and the return arrives on its
    own: no node is stranded, and ``resumed`` is empty because nothing needed repairing.
    """
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [
                        _perform("PB"),
                        {"type": "PERFORM", "operands": ["PA"], "thru": "PC"},
                        _perform("Q1"),
                        _perform("Q2"),
                        _move("'Z'", "WS-AFTER"),
                    ],
                },
                {"name": "PA", "statements": [_move("'A'", "WS-A")]},
                {"name": "PB", "statements": [_move("'B'", "WS-B")]},
                {"name": "PC", "statements": [_move("'C'", "WS-C")]},
                {"name": "Q1", "statements": [_move("'1'", "WS-Q1")]},
                {"name": "Q2", "statements": [_move("'2'", "WS-Q2")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-Q1")) == ((),)
    assert guards_of(reaching, _writer_of(cfg, "WS-Q2")) == ((),)
    assert guards_of(reaching, _writer_of(cfg, "WS-AFTER")) == ((),)
    assert reaching.abandoned == frozenset()
    assert reaching.resumed == frozenset()


def test_the_walk_resumes_past_a_call_whose_return_the_cap_swallowed(asg_of) -> None:
    """The cap can falsify the prediction that a call's RETURN will fire. Then the walk
    has to take the FLOW edge it refused on the strength of that prediction.

    Two PERFORMs of one paragraph, walked with room for a single arrival per node, is
    the whole pathology in eight nodes:

        MAIN.     PERFORM HANDLER.   <- MAIN/0
                  PERFORM HANDLER.   <- MAIN/1
                  MOVE 'A' TO WS-AFTER.
        HANDLER.  MOVE 'H' TO WS-H.

    ``MAIN/0`` takes its PERFORM, so its FLOW edge to ``MAIN/1`` is refused -- the
    paragraph's RETURN goes there. That return fires, and ``MAIN/1`` is reached. But the
    single arrival HANDLER was allowed is now spent, so ``MAIN/1``'s own PERFORM finds no
    room, the second activation never happens, and no second RETURN ever lands on
    ``MAIN/2``. ``MAIN/1``'s FLOW edge to ``MAIN/2`` was refused on the strength of
    exactly that return.

    So the loss is not the one arrival the cap declined. It is ``WS-AFTER`` and MAIN's
    end and everything the fall-through cascade reaches after them -- a partial answer
    inside HANDLER turned into no answer at all for the rest of the program. That is the
    shape measured on a real member as 55 of 114 paragraphs reporting nothing, cascading
    up through the returns of the calls that contained the one that hit the cap.

    ``resumed`` naming ``MAIN/2`` is what proves the repair rather than merely observing
    the recovery: a node is named there only if the sweep left it unreached and the
    resume seeded it. Its guard is the call's own, which is what a returning paragraph
    hands back.
    """
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [
                        _perform("HANDLER"),
                        _perform("HANDLER"),
                        _move("'A'", "WS-AFTER"),
                    ],
                },
                {"name": "HANDLER", "statements": [_move("'H'", "WS-H")]},
            )
        )
    )

    reaching = reaching_conditions(cfg, max_paths=1)

    after = _writer_of(cfg, "WS-AFTER")
    assert reaching.resumed == frozenset({after})
    assert guards_of(reaching, after) == ((),)
    assert guards_of(reaching, end_id("MAIN")) == ((),)
    assert label_id("HANDLER") in reaching.overflowed


def test_nothing_is_resumed_when_every_predicted_return_fires(asg_of) -> None:
    """The same program with room to walk it: the resume is a repair for a cap that ran
    out, not a second opinion on the graph. Left on unconditionally it would report the
    statement after every call twice, once per route, and the duplicates would fill the
    cap -- which is the loss it exists to undo."""
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [
                        _perform("HANDLER"),
                        _perform("HANDLER"),
                        _move("'A'", "WS-AFTER"),
                    ],
                },
                {"name": "HANDLER", "statements": [_move("'H'", "WS-H")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert reaching.resumed == frozenset()
    assert reaching.overflowed == frozenset()
    assert guards_of(reaching, _writer_of(cfg, "WS-AFTER")) == ((),)


def test_a_resumed_walk_returns_to_the_call_that_reached_it(asg_of) -> None:
    """A resumed walk carries the frames of the walk that was refused, not none.

    The stranded continuation is now INSIDE a performed paragraph, one level down::

        MAIN.     IF WS-FLAG = 'Y'
                      PERFORM OUTER
                  END-IF.
                  MOVE 'M' TO WS-MAIN-TAIL.
        OUTER.    PERFORM HANDLER.  PERFORM HANDLER.  PERFORM HANDLER.
                  MOVE 'O' TO WS-OUTER-TAIL.
        HANDLER.  MOVE 'H' TO WS-H.

    With room for two arrivals, HANDLER is entered by the first two calls and the third
    finds none, so ``WS-OUTER-TAIL`` is the stranded continuation and gets resumed.

    ``WS-MAIN-TAIL`` is the witness, and it is a witness because its two guards arrive by
    two different routes. The FALSE guard comes down the branch that skipped the call.
    The TRUE guard can ONLY arrive by returning out of ``OUTER#end``, since the call's own
    FLOW edge is refused -- and ``OUTER#end`` is only reached at all because the resume
    restarted the walk at ``WS-OUTER-TAIL``. Seed that walk with no frames and it lands in
    OUTER as if control had fallen in from above: OUTER's end takes its FALLTHRU to
    HANDLER instead of its RETURN, the return is refused for belonging to no frame, and
    ``WS-MAIN-TAIL`` reads as running only when the call was skipped. Carrying both
    polarities is proof the frames came along.
    """
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [
                        _if(_rel("WS-FLAG", "'Y'"), [_perform("OUTER")]),
                        _move("'M'", "WS-MAIN-TAIL"),
                    ],
                },
                {
                    "name": "OUTER",
                    "statements": [
                        _perform("HANDLER"),
                        _perform("HANDLER"),
                        _perform("HANDLER"),
                        _move("'O'", "WS-OUTER-TAIL"),
                    ],
                },
                {"name": "HANDLER", "statements": [_move("'H'", "WS-H")]},
            )
        )
    )

    reaching = reaching_conditions(cfg, max_paths=2)

    assert _writer_of(cfg, "WS-OUTER-TAIL") in reaching.resumed
    assert _kinds_of_each(reaching, _writer_of(cfg, "WS-MAIN-TAIL")) == [
        [EdgeKind.FALSE.value],
        [EdgeKind.TRUE.value],
    ]


def test_a_performed_paragraph_ends_by_returning_and_not_by_falling_through(
    asg_of,
) -> None:
    """The two edges leaving a performed paragraph's end are not interchangeable.

    The RETURN is what executes when control arrived through a PERFORM; the FALLTHRU
    into the next paragraph executes when control arrived in a straight line. Which one
    it is depends on the frames the path is inside, so the walk decides from its own
    stack rather than from the graph -- deciding it from the graph is what made the call
    at MAIN/0 refuse its FLOW edge and zero everything after it.

    The PERFORM sits under an IF, and the statement after the IF is the witness. Its
    FALSE guard arrives down the branch that skipped the call; its TRUE guard can ONLY
    arrive by returning out of DRIVER's end, because the call's own FLOW edge is refused
    while a return onto it can still fire. Carrying both is therefore proof the return
    fired. Fall through inside the frame instead and the walk leaves DRIVER for the next
    paragraph, never comes back, and the statement after the IF reads as running only
    when the call was skipped.
    """
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [
                        _if(_rel("WS-FLAG", "'Y'"), [_perform("DRIVER")]),
                        _move("'S'", "WS-STOP"),
                    ],
                },
                {
                    "name": "DRIVER",
                    "statements": [
                        _perform("PB"),
                        {"type": "PERFORM", "operands": ["PA"], "thru": "PC"},
                        _move("'D'", "WS-D"),
                    ],
                },
                {"name": "AFTER", "statements": [_move("'N'", "WS-AFTER")]},
                {"name": "PA", "statements": [_move("'a'", "WS-A")]},
                {"name": "PB", "statements": [_move("'b'", "WS-B")]},
                {"name": "PC", "statements": [_move("'c'", "WS-C")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert _kinds_of_each(reaching, _writer_of(cfg, "WS-STOP")) == [
        [EdgeKind.FALSE.value],
        [EdgeKind.TRUE.value],
    ]
    assert reaching.abandoned == frozenset()


def test_a_perform_that_can_never_return_still_reaches_the_next_statement(
    asg_of,
) -> None:
    """The same rule from the other end: PA's only statement is a GO TO, so nothing
    in the graph reaches PA#end and the return edge hanging off it can never fire.
    The statement after the call is reached by the FLOW edge or by nothing at all."""
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [
                        _perform("PX"),
                        _perform("PA"),
                        _move("'Z'", "WS-AFTER"),
                    ],
                },
                {"name": "PA", "statements": [_goto("PX")]},
                {"name": "PX", "statements": [_move("'X'", "WS-X")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-AFTER")) == ((),)


def test_a_perform_of_an_undeclared_paragraph_still_continues(asg_of) -> None:
    """The target is in a copybook the parse could not resolve, so there is no
    PERFORM edge to follow. Suppressing the FLOW edge there would report the rest of
    the paragraph unreachable -- losing every definition after it."""
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [_perform("NOWHERE"), _move("'A'", "WS-AFTER")],
                }
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-AFTER")) == ((),)


def test_a_paragraph_reached_only_by_a_goto_still_gets_guards(asg_of) -> None:
    """11% of paragraphs on a real corpus are never PERFORMed and hold 5% of the
    assignments. A walk that only followed perform edges would report them
    unreachable and lose those definitions."""
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [_if(_rel("WS-FLAG-A", "'Y'"), [_goto("LAND")])],
                },
                {"name": "LAND", "statements": [_move("'A'", "WS-RESULT")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-RESULT"))


def test_a_loop_body_is_walked_once_rather_than_forever(program_of) -> None:
    """No node repeats on a path, so a PERFORM UNTIL terminates. The answer wanted
    is "under what condition does this run at all", not one guard per iteration."""
    cfg = build_program(
        program_of(
            [
                {
                    "type": "PERFORM",
                    "perform_type": "UNTIL",
                    "until": _rel("WS-FLAG-A", "'Y'"),
                    "children": [_move("'A'", "WS-RESULT")],
                }
            ]
        )
    )

    reaching = reaching_conditions(cfg)
    guards = guards_of(reaching, _writer_of(cfg, "WS-RESULT"))

    assert [_kinds(guard) for guard in guards] == [[EdgeKind.FALSE]]


def test_an_unreachable_node_has_no_guards_rather_than_an_empty_one(asg_of) -> None:
    """Zero guards and one empty guard are opposite claims. A paragraph nothing
    reaches gets zero, and nothing manufactures a guard to fill the gap."""
    cfg = build_program(
        asg_of(
            _program(
                {"name": "MAIN", "statements": [_goto("THIRD")]},
                {"name": "ORPHAN", "statements": [_move("'A'", "WS-ORPHANED")]},
                {"name": "THIRD", "statements": [_move("'B'", "WS-RESULT")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-ORPHANED")) == ()
    assert guards_of(reaching, _writer_of(cfg, "WS-RESULT")) == ((),)


def test_real_dead_code_is_not_named_abandoned(asg_of) -> None:
    """``abandoned`` is the other half of the same distinction: nothing here leads to
    ORPHAN, so no node next to it carries a guard either, and the zero it reports is a
    statement about the program. Dead code is a finding worth keeping, so it must not
    be swept in with the nodes the walk gave up on."""
    cfg = build_program(
        asg_of(
            _program(
                {"name": "MAIN", "statements": [_goto("THIRD")]},
                {"name": "ORPHAN", "statements": [_move("'A'", "WS-ORPHANED")]},
                {"name": "THIRD", "statements": [_move("'B'", "WS-RESULT")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert reaching.abandoned == frozenset()


def test_a_paragraph_performed_from_inside_its_own_range_still_reaches_the_range_end(
    asg_of,
) -> None:
    """The loss that motivated ``abandoned``, now recovered by walking activations.

    PB is performed from inside the range of the PERFORM of PA THRU PC, so control
    reaches PC by returning to PA's end, falling through PB a SECOND time and on into
    PC. A path-wide no-repeat rule walks PB once and loses that route: PC came out with
    no guards, the cap uninvolved, and silence presents a live paragraph as dead code.

    Scoping the no-repeat rule to the activation is what recovers it -- the fall-through
    entry into PB is a different activation from the PERFORM's, so it is not a repeat.
    Nothing is given up on, so ``abandoned`` is empty, which is the answer that says the
    walk lost nothing rather than the answer that says the program is dead.
    """
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [
                        {"type": "PERFORM", "operands": ["PA"], "thru": "PC"},
                        _move("'Z'", "WS-AFTER"),
                    ],
                },
                {"name": "PA", "statements": [_perform("PB")]},
                {"name": "PB", "statements": [_move("'B'", "WS-B")]},
                {"name": "PC", "statements": [_move("'C'", "WS-C")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert reaching.truncated == frozenset()
    assert reaching.abandoned == frozenset()
    assert guards_of(reaching, _writer_of(cfg, "WS-B")) == ((),)
    assert guards_of(reaching, _writer_of(cfg, "WS-C")) == ((),)
    assert guards_of(reaching, _writer_of(cfg, "WS-AFTER")) == ((),)


def test_a_node_that_hit_the_path_cap_is_named_as_truncated(program_of) -> None:
    """A silently capped answer is a wrong answer with no warning: it reads as a
    complete list of the conditions under which a field is written."""
    ifs = [
        _if(_rel(f"WS-FLAG-{n}", "'Y'"), [_move("'A'", f"WS-X{n}")]) for n in range(12)
    ]
    cfg = build_program(program_of([*ifs, _move("'Z'", "WS-LAST")]))

    reaching = reaching_conditions(cfg, max_paths=8)

    assert len(guards_of(reaching, _writer_of(cfg, "WS-LAST"))) <= 8
    assert _writer_of(cfg, "WS-LAST") in reaching.truncated


def test_truncation_carries_forward_to_the_nodes_after_the_capped_one(
    program_of,
) -> None:
    """The walks the cap refused were never expanded, so the nodes after the capped
    one are short of those paths too. Naming only the node that overflowed lets a
    reader treat the next node's guards as the complete answer -- and none of the
    downstream nodes overflows on its own here, because the cap already stopped
    feeding them.

    The tail is four statements long on purpose. Only the first is a single hop from a
    node in ``overflowed``, so a closure that took one step and stopped would still
    flag it; the fourth is reached only by following the chain, which is the transitive
    property the closure exists to have.
    """
    ifs = [
        _if(_rel(f"WS-FLAG-{n}", "'Y'"), [_move("'A'", f"WS-X{n}")]) for n in range(12)
    ]
    tail = [_move("'Z'", "WS-LAST"), *(_move("'Y'", f"WS-HOP{n}") for n in range(1, 4))]
    cfg = build_program(program_of([*ifs, *tail]))

    reaching = reaching_conditions(cfg, max_paths=8)
    hops = [_writer_of(cfg, f"WS-HOP{n}") for n in range(1, 4)]

    assert _writer_of(cfg, "WS-LAST") in reaching.overflowed
    assert [node_id in reaching.overflowed for node_id in hops] == [False] * 3
    assert [len(guards_of(reaching, node_id)) for node_id in hops] == [8] * 3
    assert [node_id in reaching.truncated for node_id in hops] == [True] * 3
    assert end_id("MAIN") in reaching.truncated


def test_a_program_under_the_cap_truncates_nothing(program_of) -> None:
    cfg = build_program(
        program_of(
            [
                _if(_rel("WS-FLAG-A", "'Y'"), [_move("'A'", "WS-X")]),
                _move("'B'", "WS-AFTER"),
            ]
        )
    )

    assert reaching_conditions(cfg).truncated == frozenset()


def test_the_default_cap_is_the_documented_constant() -> None:
    assert MAX_PATHS == 64


def test_guard_set_drops_order_so_two_orders_of_the_same_tests_compare_equal() -> None:
    """Co-assignment asks whether two writes are guarded the same way, and the order
    two independent tests were written in is not part of that question."""
    guard_a = (("MAIN/0#test", EdgeKind.TRUE), ("MAIN/1#test", EdgeKind.FALSE))
    guard_b = (("MAIN/1#test", EdgeKind.FALSE), ("MAIN/0#test", EdgeKind.TRUE))

    assert guard_set(guard_a) == guard_set(guard_b)


def test_guard_text_renders_a_polarity_as_a_readable_predicate(program_of) -> None:
    """The rendering is what a human reads in a derivation, so a FALSE edge has to
    say NOT rather than showing the atom that was tested with no polarity at all."""
    cfg = build_program(
        program_of([_if(_rel("WS-FLAG-A", "'Y'"), [], [_move("'B'", "WS-RESULT")])])
    )
    reaching = reaching_conditions(cfg)
    (guard,) = guards_of(reaching, _writer_of(cfg, "WS-RESULT"))

    rendered = guard_text(cfg, guard)

    assert len(rendered) == 1
    assert rendered[0].startswith("NOT ")
    assert "WS-FLAG-A" in rendered[0]


def test_an_unresolvable_predicate_survives_in_the_guard_and_renders(
    program_of,
) -> None:
    """Dropping a predicate the pass could not decompose STRENGTHENS the guard: it
    claims the write happens under fewer conditions than it does. So an unreadable
    test keeps its step and its rendered term says it is unreadable."""
    cfg = build_program(
        program_of([_if({"something": "new"}, [_move("'A'", "WS-RESULT")])])
    )
    test_node = next(node for node in cfg.nodes if node.kind == NodeKind.TEST)
    assert test_node.atom.resolved is False

    reaching = reaching_conditions(cfg)
    (guard,) = guards_of(reaching, _writer_of(cfg, "WS-RESULT"))

    assert guard == ((test_node.id, EdgeKind.TRUE),)
    assert guard_text(cfg, guard) == ("UNRESOLVED",)


def test_an_unresolved_atom_that_reads_like_a_predicate_is_still_marked() -> None:
    """The desugaring emits unresolved atoms with text in them -- the arm of an ON
    EXCEPTION, a SEARCH whose outcome is unknown. Rendering those as though they were
    understood is the same dishonesty as dropping them, just quieter, so the mark is
    on ``resolved`` and not on whether the text happens to be empty."""
    node = Node(
        id="MAIN/0#test",
        kind=NodeKind.TEST,
        paragraph="MAIN",
        atom=Atom(text="INVALID KEY ", resolved=False),
    )
    cfg = Cfg(program="PROGA", nodes=(node,), edges=())

    assert guard_text(cfg, ((node.id, EdgeKind.TRUE),)) == ("UNRESOLVED: INVALID KEY",)
    assert guard_text(cfg, ((node.id, EdgeKind.FALSE),)) == (
        "NOT (UNRESOLVED: INVALID KEY)",
    )


def test_a_test_node_records_the_guards_that_reach_it_not_its_own_polarity(
    program_of,
) -> None:
    """A test's own answer is not known until it runs, so its guard is what reached
    it -- otherwise every nested test would double-count itself."""
    cfg = build_program(
        program_of(
            [
                _if(
                    _rel("WS-FLAG-A", "'Y'"),
                    [_if(_rel("WS-FLAG-B", "'Y'"), [_move("'A'", "WS-X")])],
                )
            ]
        )
    )

    reaching = reaching_conditions(cfg)
    inner = next(
        node
        for node in cfg.nodes
        if node.kind == NodeKind.TEST and "WS-FLAG-B" in node.atom.text
    )

    assert [_kinds(guard) for guard in guards_of(reaching, inner.id)] == [
        [EdgeKind.TRUE]
    ]


def test_the_entry_is_the_first_paragraphs_label(asg_of) -> None:
    cfg = build_program(
        asg_of(
            _program(
                {"name": "MAIN", "statements": [_move("'A'", "WS-A")]},
                {"name": "SECOND", "statements": []},
            )
        )
    )

    assert entry_of(cfg) == label_id("MAIN")
    assert guards_of(reaching_conditions(cfg), label_id("MAIN")) == ((),)


def test_the_entry_is_the_implicit_paragraph_when_the_source_has_one(asg_of) -> None:
    """Statements before the first paragraph run first, so the walk has to start
    there -- starting at the first named paragraph would report them unreached."""
    cfg = build_program(
        asg_of(
            {
                "program_id": "PROGA",
                "statements": [_move("'A'", "WS-A")],
                "paragraphs": [{"name": "MAIN", "statements": []}],
            }
        )
    )

    assert entry_of(cfg) == label_id(IMPLICIT_FIRST)
    assert guards_of(reaching_conditions(cfg), _writer_of(cfg, "WS-A")) == ((),)


def test_an_empty_program_answers_nothing_rather_than_failing(asg_of) -> None:
    cfg = Cfg(program="PROGA", nodes=(), edges=())

    reaching = reaching_conditions(cfg)

    assert entry_of(cfg) == ""
    assert reaching.guards == {}
    assert reaching.truncated == frozenset()


def test_a_paragraph_end_is_reached_under_the_guards_of_its_last_statements(
    program_of,
) -> None:
    """The #end node is the join every caller reads back through, so it has to carry
    the union of the arms rather than the guard of the last arm lowered."""
    cfg = build_program(
        program_of(
            [
                _if(
                    _rel("WS-FLAG-A", "'Y'"),
                    [_move("'A'", "WS-X")],
                    [_move("'B'", "WS-Y")],
                )
            ]
        )
    )

    reaching = reaching_conditions(cfg)
    guards = guards_of(reaching, end_id("MAIN"))

    assert sorted(_kinds(guard)[0].value for guard in guards) == ["FALSE", "TRUE"]


def test_a_return_to_anything_but_the_calls_resume_is_not_taken() -> None:
    """F10: the RETURN rule admits an edge only if its target is where the node on
    top of the stack resumes, and nothing else pins that.

    build_program cannot produce a counter-example: RETURN edges are created only at a
    PERFORM node, sourced at the range end and targeting the node's resume, so every
    RETURN target is already its call's resume. The filter is therefore unexercised by
    generated graphs rather than dead -- it is what makes _continuations mean "where
    the call resumes", and _returns_from reads the same helper to decide whether a
    FALLTHRU is a return in disguise. Widen it and that refusal fires more often,
    which is the direction _passable's contract calls the worse failure. So it is
    pinned here with a graph built by hand.

    MAIN/0 resumes at MAIN/2. MAIN/1 is reachable only through a RETURN out of the
    range end that is not to the call's resume. It must stay unreached -- and visibly
    so, through `abandoned`, because a walk that declined a route is not a program
    with dead code.
    """
    cfg = Cfg(
        program="PROGA",
        nodes=(
            Node(
                id="MAIN/0",
                kind=NodeKind.CALL,
                paragraph="MAIN",
                transfer="PERFORM",
                target="P-ONE",
                resume="MAIN/2",
            ),
            Node(id="P-ONE#label", kind=NodeKind.LABEL, paragraph="P-ONE"),
            Node(
                id="P-ONE/0", kind=NodeKind.ASSIGN, paragraph="P-ONE", writes=("WS-A",)
            ),
            Node(id="P-ONE#end", kind=NodeKind.NOP, paragraph="P-ONE"),
            Node(id="MAIN/1", kind=NodeKind.ASSIGN, paragraph="MAIN", writes=("WS-B",)),
            Node(id="MAIN/2", kind=NodeKind.NOP, paragraph="MAIN"),
        ),
        edges=(
            Edge(source="MAIN/0", target="P-ONE#label", kind=EdgeKind.PERFORM),
            Edge(source="MAIN/0", target="MAIN/1", kind=EdgeKind.RETURN),
            Edge(source="P-ONE#label", target="P-ONE/0", kind=EdgeKind.FLOW),
            Edge(source="P-ONE/0", target="P-ONE#end", kind=EdgeKind.FLOW),
            Edge(source="P-ONE#end", target="MAIN/1", kind=EdgeKind.RETURN),
        ),
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, "MAIN/1") == ()
    assert "MAIN/1" in reaching.abandoned


def test_a_perform_the_recursion_guard_bars_is_stepped_over_to_its_resume(
    asg_of,
) -> None:
    """A paragraph may not be performed from inside itself, so the inner PERFORM is
    barred -- and a resolved PERFORM has no edge past it. The walk steps to where it
    would resume instead -- directly, so nothing after it is a guess the second pass
    had to recover."""
    cfg = build_program(
        asg_of(
            _program(
                {"name": "MAIN", "statements": [_perform("AGAIN")]},
                {
                    "name": "AGAIN",
                    "statements": [_perform("AGAIN"), _move("'A'", "WS-AFTER")],
                },
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-AFTER")) == ((),)
    assert reaching.resumed == frozenset()
