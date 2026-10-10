"""Acceptance: DISP values and their defaults."""

from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_disp_parses(parse_fixture):
    from jackal.model import Job
    from jackal.model import NotCoded
    from tests.acceptance import build as b

    d = b.disp
    assert parse_fixture("disp/disp.jcl") == Job(
        "ACCEPT",
        (
            b.pgm(
                "S1",
                "PGMA",
                (
                    b.dataset("A", "T.A", d("NEW", "DELETE", "DELETE")),
                    b.dataset("B", "T.B", d("OLD", "KEEP", "KEEP")),
                    b.dataset("C", "T.C", d("SHR", "KEEP", "KEEP")),
                    b.dataset("D", "T.D", d("MOD", "KEEP", "KEEP")),
                    b.dataset("E", "T.E", d("NEW", "CATLG", "DELETE")),
                    b.dataset("F", "T.F", d("OLD", "UNCATLG", "UNCATLG")),
                    b.dataset("G", "T.G", d("NEW", "PASS", "DELETE")),
                    b.dataset("H", "T.H", d("OLD", "PASS", "KEEP")),
                    b.dataset("I", "T.I", d("OLD", "DELETE", "KEEP")),
                    b.dataset("J", "T.J", NotCoded()),
                    b.dataset("K", "T.K", d("NEW", "KEEP", "UNCATLG")),
                ),
            ),
        ),
    )
