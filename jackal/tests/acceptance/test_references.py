"""Acceptance: how references resolve in each scope."""

from tests.acceptance.markers import EXPANDED
from tests.covers import NotLanguageFeature, covers


@EXPANDED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_reference_inside_proc_expands(expand_fixture, parse_fixture):
    from jackal.expansion import ExpandedJob
    from tests.acceptance import build as b

    steps = parse_fixture("refs/refs.jcl").steps
    s1_call, s3_call = steps[1], steps[3]
    s0 = b.qualified((), b.pgm("S0", "PGMZ"))

    def run(call: object) -> tuple[object, object]:
        p1 = b.qualified((call,), b.pgm("P1", "PGMA"))
        p2 = b.qualified(
            (call,),
            b.pgm(
                "P2",
                "PGMB",
                condition=b.cond(b.on_step(0, "NE", p1), b.on_step(4, "LT", s0)),
            ),
        )
        return p1, p2

    first_p1, first_p2 = run(s1_call)
    second_p1, second_p2 = run(s3_call)
    s2 = b.qualified(
        (),
        b.pgm(
            "S2",
            "PGMC",
            condition=b.cond(b.on_step(4, "LT", first_p2), b.on_step(8, "LT", s0)),
        ),
    )
    assert expand_fixture("refs/refs.jcl") == ExpandedJob(
        "ACCEPT", (s0, first_p1, first_p2, s2, second_p1, second_p2)
    )
