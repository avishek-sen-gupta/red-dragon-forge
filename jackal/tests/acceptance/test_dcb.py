"""Acceptance: every DCB form parses, and the job around it is intact."""

from tests.acceptance.markers import bridge_then_parsed
from tests.covers import NotLanguageFeature, covers


@bridge_then_parsed("red-dragon-forge-2cy.2")
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dcb_forms_parse(parse_fixture):
    from jackal.model import Job
    from tests.acceptance import build as b

    new_catlg = b.disp("NEW", "CATLG", "CATLG")
    assert parse_fixture("dcb/dcb.jcl") == Job(
        "ACCEPT",
        (
            b.pgm(
                "S1",
                "PGMA",
                (
                    b.dataset("A", "T.A", new_catlg),
                    b.dataset("B", "T.B", new_catlg),
                    b.dataset("C", "T.C", new_catlg),
                    b.dataset("D", "T.D", new_catlg),
                ),
            ),
            b.pgm("S2", "PGMB", (b.dataset("E", "T.A"),)),
        ),
    )
