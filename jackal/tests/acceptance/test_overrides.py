"""Acceptance: COND, PARM and DD overrides on a PROC call."""

from tests.acceptance.markers import bridge_then_expanded, bridge_then_parsed
from tests.covers import NotLanguageFeature, covers


@bridge_then_parsed("red-dragon-forge-2cy.12")
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_overrides_parse(parse_fixture):
    from jackal.model import Job, ProcCall, ProcStepOverrides
    from jackal.value_parts import literal
    from tests.acceptance import build as b

    p1, p2 = b.name("P1"), b.name("P2")
    assert parse_fixture("overrides/overrides.jcl") == Job(
        "ACCEPT",
        (
            ProcCall(b.name("S1"), "TWO", parm_for_first_step=literal("X")),
            ProcCall(
                b.name("S2"),
                "TWO",
                per_step=((p2, ProcStepOverrides(parm=literal("Y"))),),
            ),
            ProcCall(
                b.name("S3"),
                "TWO",
                parm_for_first_step=literal("X"),
                per_step=((p2, ProcStepOverrides(parm=literal("Y"))),),
            ),
            ProcCall(
                b.name("S4"), "TWO", cond_for_every_step=b.cond(b.all_prior(4, "LT"))
            ),
            ProcCall(
                b.name("S5"),
                "TWO",
                per_step=((p2, ProcStepOverrides(cond=b.cond(b.all_prior(0, "NE")))),),
            ),
            ProcCall(b.name("S6"), "TWO", per_step=((p1, ProcStepOverrides(parm=())),)),
            ProcCall(
                b.name("S7"),
                "TWO",
                dds_for_first_step=(b.dataset("IN", "T.NEWIN"),),
                per_step=(
                    (
                        p2,
                        ProcStepOverrides(
                            dds=(
                                b.dataset("OUT", "T.NEWOUT"),
                                b.dataset("EXTRA", "T.EXTRA"),
                            )
                        ),
                    ),
                ),
            ),
        ),
    )


@bridge_then_expanded("red-dragon-forge-2cy.12")
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_overrides_expand(expand_fixture, parse_fixture):
    from jackal.expansion import ExpandedJob
    from tests.acceptance import build as b

    calls = parse_fixture("overrides/overrides.jcl").steps
    p1_in = b.dataset("IN", "T.P1IN")
    p2_dds = (b.dataset("OUT", "T.P2OUT"), b.dataset("LOG", "T.P2LOG"))
    p1_cond = b.cond(b.all_prior(8, "LT"))

    def run(
        call: object,
        p1_parm: str,
        p2_parm: str,
        p1_condition: object = p1_cond,
        p2_condition: object = b.NO_COND,
        p1_dds: tuple[object, ...] = (p1_in,),
        p2_dds_: tuple[object, ...] = p2_dds,
    ) -> tuple[object, ...]:
        return (
            b.qualified((call,), b.pgm("P1", "PGMA", p1_dds, p1_condition, p1_parm)),
            b.qualified((call,), b.pgm("P2", "PGMB", p2_dds_, p2_condition, p2_parm)),
        )

    every = b.cond(b.all_prior(4, "LT"))
    assert expand_fixture("overrides/overrides.jcl") == ExpandedJob(
        "ACCEPT",
        (
            *run(calls[0], "X", ""),
            *run(calls[1], "ONE", "Y"),
            *run(calls[2], "X", "Y"),
            *run(calls[3], "ONE", "TWO", every, every),
            *run(calls[4], "ONE", "TWO", p2_condition=b.cond(b.all_prior(0, "NE"))),
            *run(calls[5], "", "TWO"),
            *run(
                calls[6],
                "ONE",
                "TWO",
                p1_dds=(b.dataset("IN", "T.NEWIN"),),
                p2_dds_=(
                    b.dataset("OUT", "T.NEWOUT"),
                    b.dataset("LOG", "T.P2LOG"),
                    b.dataset("EXTRA", "T.EXTRA"),
                ),
            ),
        ),
    )
