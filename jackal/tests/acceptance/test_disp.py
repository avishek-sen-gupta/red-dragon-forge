"""Acceptance: DISP values and their defaults."""

from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_disp_parses(parse_fixture):
    from jackal.model import Job, NotCoded
    from tests.acceptance import build as b

    d = b.disp
    assert parse_fixture("disp/disp.jcl") == Job(
        "ACCEPT",
        (
            b.pgm(
                "S1",
                "PGMA",
                (
                    b.dataset("A", "T.A", d("NEW")),
                    b.dataset("B", "T.B", d("OLD")),
                    b.dataset("C", "T.C", d("SHR")),
                    b.dataset("D", "T.D", d("MOD")),
                    b.dataset("E", "T.E", d("NEW", "CATLG", "DELETE")),
                    b.dataset("F", "T.F", d("OLD", "UNCATLG")),
                    b.dataset("G", "T.G", d("NEW", "PASS")),
                    b.dataset("H", "T.H", d("OLD", "PASS")),
                    b.dataset("I", "T.I", d("OLD", "DELETE", "KEEP")),
                    b.dataset("J", "T.J", NotCoded()),
                    b.dataset("K", "T.K", d("NEW", "KEEP", "UNCATLG")),
                ),
            ),
        ),
    )
