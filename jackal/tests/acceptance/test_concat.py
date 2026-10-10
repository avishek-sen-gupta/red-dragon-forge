"""Acceptance: DD concatenation."""

from tests.acceptance.markers import PARSED
from tests.covers import NotLanguageFeature, covers


@PARSED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_concatenation_parses(parse_fixture):
    from jackal.dsn import DummyDSN, InStreamDSN
    from jackal.model import ConcatMember, Job
    from tests.acceptance import build as b

    assert parse_fixture("concat/concat.jcl") == Job(
        "ACCEPT",
        (
            b.pgm(
                "S1",
                "PGMA",
                (
                    b.concat("TWO", "T.A", (b.member("T.B"),)),
                    b.concat("THREE", "T.C", (b.member("T.D"), b.member("T.E"))),
                    b.concat(
                        "MIXED",
                        "T.F",
                        (
                            ConcatMember(InStreamDSN(), b.DEFAULT_DISP, (" CARD",)),
                            ConcatMember(DummyDSN(), b.DEFAULT_DISP),
                        ),
                    ),
                    b.dataset("LAST", "T.G"),
                ),
            ),
        ),
    )
