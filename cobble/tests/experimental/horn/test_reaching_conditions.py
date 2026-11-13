from collections.abc import Callable, Sequence

import pytest
from cobble.dataflow.srccfg.cfg import NodeKind
from cobble.experimental.horn.answer import Answer
from cobble.experimental.horn.lower import HornSystem
from cobble.experimental.horn.outcome import Outcome
from cobble.experimental.horn.point import Point
from cobble.experimental.horn.reaching_conditions import (
    CheckedWay,
    Report,
    RouteTest,
    RouteVerdict,
    classified,
    reaching_conditions,
)
from cobble.experimental.horn.reaches import Asked
from cobble.experimental.horn.verdict import Verdict
from cobble.experimental.horn.ways import Decision, Way
from tests.experimental.horn.asg_builder import (
    STOP,
    X_OUT,
    branch_on,
    clock,
    first_byte,
    goto,
    if_,
    move_literal,
    perform,
    program,
    writer,
    x,
)


def _either(test: str) -> RouteTest:
    return RouteTest(test, RouteVerdict.EITHER_WAY, Outcome.UNRUN)


def test_a_way_with_contradictory_tests_is_dropped() -> None:
    p = program([("MAIN", [if_("F", "'A'", [if_("F", "'B'", [X_OUT])]), STOP])])
    node = writer(p, "X-OUT")

    assert reaching_conditions(p, node, clock()) == Report("PROGA", node, (), 1, False)


def test_a_flag_set_in_a_performed_paragraph_decides_a_later_test() -> None:
    p = program(
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
    node = writer(p, "X-OUT")
    g, f = branch_on(p, "G", "'N'"), branch_on(p, "F", "'Y'")

    assert reaching_conditions(p, node, clock()) == Report(
        "PROGA",
        node,
        (
            CheckedWay(
                Way((Decision(g, Outcome.TRUE),), ()),
                Answer.SAT,
                (RouteTest(f, RouteVerdict.IF_IT_RUNS, Outcome.FALSE),),
            ),
        ),
        0,
        False,
    )


def test_a_rejoining_if_on_another_field_is_either_way() -> None:
    p = program([("MAIN", [if_("F", "'Y'", [move_literal("'Y'", "G")]), X_OUT, STOP])])
    node = writer(p, "X-OUT")

    assert reaching_conditions(p, node, clock()) == Report(
        "PROGA",
        node,
        (CheckedWay(Way((), ()), Answer.SAT, (_either(branch_on(p, "F", "'Y'")),)),),
        0,
        False,
    )


def test_an_if_repeated_on_an_unchanged_field_is_if_it_runs() -> None:
    p = program(
        [
            (
                "MAIN",
                [
                    if_("F", "'A'", [move_literal("'Y'", "G")]),
                    if_("F", "'A'", [X_OUT]),
                    STOP,
                ],
            )
        ]
    )
    node = writer(p, "X-OUT")
    first, second = sorted(
        n.id for n in p.cfg.nodes if n.kind is NodeKind.TEST and n.atom.left == "F"
    )

    assert reaching_conditions(p, node, clock()) == Report(
        "PROGA",
        node,
        (
            CheckedWay(
                Way((Decision(second, Outcome.TRUE),), ()),
                Answer.SAT,
                (RouteTest(first, RouteVerdict.IF_IT_RUNS, Outcome.TRUE),),
            ),
        ),
        0,
        False,
    )


def test_a_test_nested_in_an_impossible_branch_never_runs() -> None:
    p = program(
        [
            (
                "MAIN",
                [
                    if_(
                        "F",
                        "'A'",
                        [
                            if_(
                                "F",
                                "'B'",
                                [if_("G", "'Z'", [move_literal("'Y'", "G")])],
                            )
                        ],
                    ),
                    X_OUT,
                    STOP,
                ],
            )
        ]
    )
    node = writer(p, "X-OUT")
    fa, fb, g = (
        branch_on(p, "F", "'A'"),
        branch_on(p, "F", "'B'"),
        branch_on(p, "G", "'Z'"),
    )
    route = {
        fa: _either(fa),
        fb: RouteTest(fb, RouteVerdict.IF_IT_RUNS, Outcome.FALSE),
        g: RouteTest(g, RouteVerdict.NEVER_RUNS, Outcome.UNRUN),
    }

    assert reaching_conditions(p, node, clock()) == Report(
        "PROGA",
        node,
        (CheckedWay(Way((), ()), Answer.SAT, tuple(route[t] for t in sorted(route))),),
        0,
        False,
    )


def test_a_loop_leaves_its_last_outcome() -> None:
    p = program(
        [
            ("MAIN", [move_literal("'N'", "F")]),
            (
                "LOOP",
                [
                    if_("F", "'Y'", [goto("DONE")]),
                    move_literal("'Y'", "F"),
                    goto("LOOP"),
                ],
            ),
            ("DONE", [X_OUT, STOP]),
        ]
    )
    node = writer(p, "X-OUT")

    assert reaching_conditions(p, node, clock()) == Report(
        "PROGA",
        node,
        (
            CheckedWay(
                Way((), ()),
                Answer.SAT,
                (
                    RouteTest(
                        branch_on(p, "F", "'Y'"), RouteVerdict.IF_IT_RUNS, Outcome.TRUE
                    ),
                ),
            ),
        ),
        0,
        False,
    )


def test_a_test_on_an_unplain_atom_is_either_way() -> None:
    p = program(
        [
            (
                "MAIN",
                [if_(first_byte("F3"), "'Y'", [move_literal("'Y'", "G")]), X_OUT, STOP],
            )
        ],
        (x("F3", "X(3)"), x("G"), x("X-OUT")),
    )
    node = writer(p, "X-OUT")
    (test,) = (n.id for n in p.cfg.nodes if n.kind is NodeKind.TEST)

    assert reaching_conditions(p, node, clock()) == Report(
        "PROGA",
        node,
        (CheckedWay(Way((), ()), Answer.SAT, (_either(test),)),),
        0,
        False,
    )


def test_each_way_classifies_a_shared_test_independently() -> None:
    p = program(
        [
            (
                "MAIN",
                [if_("F", "'Y'", [goto("P")]), if_("G", "'Z'", [goto("P")]), STOP],
            ),
            ("P", [X_OUT, STOP]),
        ]
    )
    node = writer(p, "X-OUT")
    f, g = branch_on(p, "F", "'Y'"), branch_on(p, "G", "'Z'")

    assert reaching_conditions(p, node, clock()) == Report(
        "PROGA",
        node,
        (
            CheckedWay(
                Way((Decision(f, Outcome.TRUE),), ()),
                Answer.SAT,
                (RouteTest(g, RouteVerdict.NEVER_RUNS, Outcome.UNRUN),),
            ),
            CheckedWay(
                Way((Decision(f, Outcome.FALSE), Decision(g, Outcome.TRUE)), ()),
                Answer.SAT,
                (),
            ),
        ),
        0,
        False,
    )


def test_an_unknown_node_is_refused() -> None:
    p = program([("MAIN", [X_OUT, STOP])])

    with pytest.raises(ValueError, match="^NOPE is not a node of PROGA$"):
        reaching_conditions(p, "NOPE", clock())


def test_a_route_test_is_classified_by_its_two_answers() -> None:
    sat, unsat, unknown = Answer.SAT, Answer.UNSAT, Answer.UNKNOWN

    assert tuple(
        classified("T", true, false)
        for true, false in (
            (sat, sat),
            (sat, unsat),
            (unsat, sat),
            (unsat, unsat),
            (unknown, sat),
            (unsat, unknown),
        )
    ) == (
        RouteTest("T", RouteVerdict.EITHER_WAY, Outcome.UNRUN),
        RouteTest("T", RouteVerdict.IF_IT_RUNS, Outcome.TRUE),
        RouteTest("T", RouteVerdict.IF_IT_RUNS, Outcome.FALSE),
        RouteTest("T", RouteVerdict.NEVER_RUNS, Outcome.UNRUN),
        RouteTest("T", RouteVerdict.GAVE_UP, Outcome.UNRUN),
        RouteTest("T", RouteVerdict.GAVE_UP, Outcome.UNRUN),
    )


def test_a_way_the_solver_gave_up_on_leaves_its_route_unchecked() -> None:
    p = program([("MAIN", [if_("F", "'Y'", [move_literal("'Y'", "G")]), X_OUT, STOP])])
    node = writer(p, "X-OUT")

    def ask(
        system: HornSystem,
        point: Point,
        conditions: Sequence[Asked],
        clock: Callable[[], float],
    ) -> Verdict:
        return Verdict(Answer.UNKNOWN if not conditions else Answer.SAT, 0.0)

    assert reaching_conditions(p, node, clock(), ask) == Report(
        "PROGA",
        node,
        (
            CheckedWay(
                Way((), ()),
                Answer.UNKNOWN,
                (
                    RouteTest(
                        branch_on(p, "F", "'Y'"), RouteVerdict.GAVE_UP, Outcome.UNRUN
                    ),
                ),
            ),
        ),
        0,
        False,
    )


def test_a_test_a_way_passes_twice_is_checked_by_its_last_outcome() -> None:
    p = program(
        [
            ("MAIN", [perform("CHK"), perform("CHK"), X_OUT, STOP]),
            (
                "CHK",
                [
                    if_(
                        "F",
                        "'A'",
                        [move_literal("'C'", "F"), if_("G", "'Z'", [STOP])],
                        [if_("G", "'Y'", [STOP])],
                    )
                ],
            ),
        ]
    )
    node = writer(p, "X-OUT")
    f, gz, gy = (
        branch_on(p, "F", "'A'"),
        branch_on(p, "G", "'Z'"),
        branch_on(p, "G", "'Y'"),
    )
    report = reaching_conditions(p, node, clock())

    assert (
        tuple(
            (tuple((d.test, d.outcome) for d in w.way.decisions), w.answer)
            for w in report.ways
        ),
        report.dropped,
    ) == (
        (
            (
                (
                    (f, Outcome.FALSE),
                    (gy, Outcome.FALSE),
                    (f, Outcome.FALSE),
                    (gy, Outcome.FALSE),
                ),
                Answer.SAT,
            ),
            (
                (
                    (f, Outcome.TRUE),
                    (gz, Outcome.FALSE),
                    (f, Outcome.FALSE),
                    (gy, Outcome.FALSE),
                ),
                Answer.SAT,
            ),
        ),
        2,
    )
