from collections.abc import Sequence

from cobble.experimental.horn.answer import Answer
from cobble.experimental.horn.condition import Condition, Entered, Op, Took
from cobble.experimental.horn.context import Context, perform_edge, performed, top
from cobble.experimental.horn.flat import flattening, formula
from cobble.experimental.horn.leading_to import leading_to
from cobble.experimental.horn.lower import Lowering, lowering_of
from cobble.experimental.horn.outcome import Outcome
from cobble.experimental.horn.program import Program
from cobble.experimental.horn.reaches import Asked
from cobble.experimental.horn.storage import storage_of
from tests.experimental.horn.asg_builder import (
    FIELDS,
    STOP,
    X_OUT,
    branch_on,
    clock,
    goto,
    if_,
    move_literal,
    perform,
    program,
    writer,
    x,
)


def _lowering(
    p: Program,
    field: str,
    watched: Sequence[str] = (),
    outcomes: Sequence[str] = (),
    entries: Sequence[Context] = (),
) -> Lowering:
    node = writer(p, field)
    kept = leading_to(p.cfg, node)
    storage = storage_of(p, watched, (), frozenset(), kept, outcomes, entries)
    return lowering_of(p, storage)


def _ask(
    p: Program,
    field: str,
    conditions: Sequence[Asked] = (),
    watched: Sequence[str] = (),
    outcomes: Sequence[str] = (),
    entries: Sequence[Context] = (),
) -> Answer:
    lowering = _lowering(p, field, watched, outcomes, entries)
    return formula(lowering, writer(p, field)).ask(conditions, clock()).answer


def _f(value: str) -> Condition:
    return Condition("F", Op.EQ, value)


def _loops(p: Program) -> tuple[int, int]:
    found = flattening(_lowering(p, "X-OUT"), writer(p, "X-OUT")).loops[top(p.cfg)]
    return len(found.headers), len(found.knots)


def test_a_test_constrains_what_follows_and_contradictory_tests_never_meet() -> None:
    contradictory = program(
        [("MAIN", [if_("F", "'A'", [if_("F", "'B'", [X_OUT])]), STOP])]
    )
    tested = program([("MAIN", [if_("F", "'Y'", [X_OUT]), STOP])])

    assert (
        _ask(contradictory, "X-OUT"),
        _ask(tested, "X-OUT", (_f("'Y'"),), ("F",)),
        _ask(tested, "X-OUT", (_f("'N'"),), ("F",)),
    ) == (Answer.UNSAT, Answer.SAT, Answer.UNSAT)


def test_a_perform_is_inlined_and_returns_only_to_its_own_caller() -> None:
    data = (*FIELDS, x("A-OUT"), x("B-OUT"), x("P-OUT"))
    two_calls = program(
        [
            (
                "MAIN",
                [
                    if_("F", "'Y'", [perform("P"), move_literal("'a'", "A-OUT")]),
                    if_("F", "'N'", [perform("P"), move_literal("'b'", "B-OUT")]),
                    STOP,
                ],
            ),
            ("P", [if_("F", "'Y'", [move_literal("'p'", "P-OUT")])]),
        ],
        data,
    )
    flag_set_inside = program(
        [
            (
                "MAIN",
                [
                    move_literal("'N'", "G"),
                    perform("CHK"),
                    if_("G", "'N'", [X_OUT]),
                    STOP,
                ],
            ),
            ("CHK", [if_("F", "'Y'", [move_literal("'Y'", "G")])]),
        ]
    )

    assert (
        _ask(two_calls, "B-OUT", (_f("'Y'"),), ("F",)),
        _ask(two_calls, "B-OUT", (_f("'N'"),), ("F",)),
        _ask(two_calls, "A-OUT", (_f("'Y'"),), ("F",)),
        _ask(flag_set_inside, "X-OUT", (_f("'Y'"),), ("F",)),
        _ask(flag_set_inside, "X-OUT", (_f("'N'"),), ("F",)),
    ) == (Answer.UNSAT, Answer.SAT, Answer.SAT, Answer.UNSAT, Answer.SAT)


def _around(written: str) -> Program:
    """F is 'N' on the way in; only a run round the loop can change it."""
    return program(
        [
            ("MAIN", [move_literal("'N'", "F")]),
            (
                "L",
                [
                    if_("F", "'Y'", [X_OUT, STOP]),
                    move_literal("'Y'", written),
                    goto("L"),
                ],
            ),
        ]
    )


def test_a_loop_is_cut_at_its_header_freeing_only_what_its_body_writes() -> None:
    assert (
        _loops(_around("F")),
        _ask(_around("F"), "X-OUT"),
        _ask(_around("G"), "X-OUT"),
    ) == ((1, 0), Answer.SAT, Answer.UNSAT)


def _knotted(written: str) -> Program:
    """A and B loop to each other, and MAIN enters at either one."""
    return program(
        [
            ("MAIN", [move_literal("'N'", "F"), if_("G", "'Y'", [goto("B")])]),
            ("A", [if_("F", "'Y'", [X_OUT, STOP])]),
            ("B", [move_literal("'Y'", written), goto("A")]),
        ]
    )


def test_a_loop_entered_at_two_nodes_is_one_knot_freeing_what_it_writes() -> None:
    assert (
        _loops(_knotted("F")),
        _ask(_knotted("F"), "X-OUT"),
        _ask(_knotted("G"), "X-OUT"),
    ) == ((0, 1), Answer.SAT, Answer.UNSAT)


def test_outcome_and_entry_marks_hold_the_last_test_outcome_and_call_site() -> None:
    tested = program([("MAIN", [if_("F", "'Y'", [X_OUT]), STOP])])
    test = branch_on(tested, "F", "'Y'")
    called = program(
        [
            (
                "MAIN",
                [
                    move_literal("'Y'", "F"),
                    perform("SUB"),
                    move_literal("'N'", "F"),
                    perform("SUB"),
                    STOP,
                ],
            ),
            ("SUB", [if_("F", "'Y'", [X_OUT])]),
        ]
    )
    cfg = called.cfg
    sites = sorted(n.id for n in cfg.nodes if perform_edge(cfg, n.id))
    sub = performed(cfg, perform_edge(cfg, sites[0])[0])

    def took(outcome: Outcome) -> Answer:
        return _ask(tested, "X-OUT", (Took(test, outcome),), outcomes=(test,))

    def entered(call: str) -> Answer:
        return _ask(called, "X-OUT", (Entered(sub, call),), entries=(sub,))

    assert (
        took(Outcome.TRUE),
        took(Outcome.FALSE),
        took(Outcome.UNRUN),
        entered(sites[0]),
        entered(sites[1]),
    ) == (Answer.SAT, Answer.UNSAT, Answer.UNSAT, Answer.SAT, Answer.UNSAT)
