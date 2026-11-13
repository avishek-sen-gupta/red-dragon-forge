from cobble.experimental.horn.context import Context, perform_edge, performed
from cobble.experimental.horn.outcome import Outcome
from cobble.experimental.horn.program import Program
from cobble.experimental.horn.ways import MAX_WAYS, Decision, Way, Ways, ways_to
from tests.experimental.horn.asg_builder import (
    STOP,
    X_OUT,
    goto,
    if_,
    move_literal,
    perform,
    program,
    branch_in,
    branch_on,
    writer,
)


def _calls(program: Program, paragraph: str) -> tuple[str, ...]:
    cfg = program.cfg
    return tuple(
        sorted(
            n.id
            for n in cfg.nodes
            if perform_edge(cfg, n.id)
            and cfg.node(perform_edge(cfg, n.id)[0].target).paragraph == paragraph
        )
    )


def _range(program: Program, call: str) -> Context:
    return performed(program.cfg, perform_edge(program.cfg, call)[0])


def test_a_rejoining_if_is_not_a_decision() -> None:
    p = program([("MAIN", [if_("F", "'Y'", [move_literal("'Y'", "G")]), X_OUT, STOP])])

    assert ways_to(p, writer(p, "X-OUT")) == Ways((Way((), ()),), False)


def test_nested_ifs_give_one_way_through_both_decisions() -> None:
    p = program([("MAIN", [if_("F", "'Y'", [if_("G", "'Z'", [X_OUT])]), STOP])])

    assert ways_to(p, writer(p, "X-OUT")) == Ways(
        (
            Way(
                (
                    Decision(branch_on(p, "F", "'Y'"), Outcome.TRUE),
                    Decision(branch_on(p, "G", "'Z'"), Outcome.TRUE),
                ),
                (),
            ),
        ),
        False,
    )


def test_a_range_performed_from_two_call_sites_gives_two_ways() -> None:
    p = program(
        [
            ("MAIN", [if_("F", "'Y'", [perform("SUB")], [perform("SUB")]), STOP]),
            ("SUB", [X_OUT]),
        ]
    )
    test = branch_on(p, "F", "'Y'")
    first, second = _calls(p, "SUB")
    sub = _range(p, first)
    outcome = {
        e.target: Outcome.TRUE if e.kind.name == "TRUE" else Outcome.FALSE
        for e in p.cfg.successors(test)
    }

    assert ways_to(p, writer(p, "X-OUT")) == Ways(
        (
            Way((Decision(test, outcome[first]),), ((sub, first),)),
            Way((Decision(test, outcome[second]),), ((sub, second),)),
        ),
        False,
    )


def test_nested_performs_carry_both_call_sites() -> None:
    p = program([("MAIN", [perform("A"), STOP]), ("A", [perform("B")]), ("B", [X_OUT])])
    (outer,) = _calls(p, "A")
    (inner,) = _calls(p, "B")

    assert ways_to(p, writer(p, "X-OUT")) == Ways(
        (Way((), ((_range(p, outer), outer), (_range(p, inner), inner))),), False
    )


def test_a_perform_that_can_end_the_task_adds_its_return_decisions() -> None:
    p = program(
        [("MAIN", [perform("SUB"), X_OUT, STOP]), ("SUB", [if_("F", "'Y'", [STOP])])]
    )

    assert ways_to(p, writer(p, "X-OUT")) == Ways(
        (Way((Decision(branch_on(p, "F", "'Y'"), Outcome.FALSE),), ()),), False
    )


def test_the_cap_cuts_and_says_so() -> None:
    layers = 7
    paragraphs = tuple(
        (
            f"L{n}",
            [
                if_("F", "'A'", [goto(f"L{n + 1}")]),
                if_("G", "'B'", [goto(f"L{n + 1}")]),
                STOP,
            ],
        )
        for n in range(layers)
    )
    p = program([*paragraphs, (f"L{layers}", [X_OUT, STOP])])
    found = ways_to(p, writer(p, "X-OUT"))
    first = branch_in(p, "L0", "F", "'A'")

    assert (len(found.ways), len(set(found.ways)), found.cut) == (
        MAX_WAYS,
        MAX_WAYS,
        True,
    )
    assert found.ways[0].decisions[0] in (
        Decision(first, Outcome.TRUE),
        Decision(first, Outcome.FALSE),
    )


def test_an_unreachable_node_has_no_ways() -> None:
    p = program([("MAIN", [STOP, X_OUT])])

    assert ways_to(p, writer(p, "X-OUT")) == Ways((), False)
