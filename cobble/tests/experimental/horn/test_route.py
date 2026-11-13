from cobble.experimental.horn.route import route_tests
from cobble.experimental.horn.ways import ways_to
from tests.experimental.horn.asg_builder import (
    STOP,
    X_OUT,
    branch_on,
    if_,
    move_literal,
    perform,
    program,
    writer,
)


def test_route_tests_include_a_rejoining_if() -> None:
    p = program([("MAIN", [if_("F", "'Y'", [move_literal("'Y'", "G")]), X_OUT, STOP])])
    node = writer(p, "X-OUT")
    (way,) = ways_to(p, node).ways

    assert route_tests(p, way, node) == (branch_on(p, "F", "'Y'"),)


def test_route_tests_reach_into_performed_paragraphs() -> None:
    p = program(
        [
            ("MAIN", [perform("SUB"), X_OUT, STOP]),
            ("SUB", [if_("G", "'Z'", [move_literal("'Y'", "F")])]),
        ]
    )
    node = writer(p, "X-OUT")
    (way,) = ways_to(p, node).ways

    assert route_tests(p, way, node) == (branch_on(p, "G", "'Z'"),)


def test_route_tests_exclude_the_ways_decisions() -> None:
    p = program(
        [
            (
                "MAIN",
                [
                    if_("F", "'Y'", [move_literal("'Z'", "G")]),
                    if_("G", "'Z'", [X_OUT]),
                    STOP,
                ],
            )
        ]
    )
    node = writer(p, "X-OUT")
    (way,) = ways_to(p, node).ways

    assert route_tests(p, way, node) == (branch_on(p, "F", "'Y'"),)
