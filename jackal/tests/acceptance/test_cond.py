"""Acceptance: EXEC and JOB COND."""

from tests.acceptance.markers import bridge_then_parsed
from tests.covers import NotLanguageFeature, covers


@bridge_then_parsed("red-dragon-forge-2cy.11")
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cond_parses(parse_fixture):
    from jackal.model import CondOp, Job, RcComparison
    from tests.acceptance import build as b

    s1 = b.ref("S1")
    assert parse_fixture("cond/cond.jcl") == Job(
        "ACCEPT",
        (
            b.pgm("S1", "PGMA"),
            b.pgm("S2", "PGMB", condition=b.cond(b.all_prior(4, "LT"))),
            b.pgm(
                "S3",
                "PGMC",
                condition=b.cond(b.all_prior(4, "LT"), b.on_step(8, "EQ", s1)),
            ),
            b.pgm(
                "S4", "PGMD", condition=b.cond(b.on_step(4, "LT", b.ref_in("S1", "P1")))
            ),
            b.pgm("S5", "PGME", condition=b.cond(mode="EVEN")),
            b.pgm("S6", "PGMF", condition=b.cond(mode="ONLY")),
            b.pgm(
                "S7",
                "PGMG",
                condition=b.cond(
                    b.all_prior(4, "LT"), b.on_step(8, "EQ", s1), mode="EVEN"
                ),
            ),
            b.pgm("S8", "PGMH", condition=b.cond(b.all_prior(4, "LT"), mode="ONLY")),
        ),
        end_job_tests=(RcComparison(8, CondOp.LE), RcComparison(12, CondOp.EQ)),
    )
