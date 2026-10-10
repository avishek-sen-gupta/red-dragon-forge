"""Acceptance: every DSN kind, and temps and referbacks after expansion."""

from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dsn_kinds_parse(parse_fixture):
    from jackal.model import Job
    from tests.acceptance import build as b

    assert parse_fixture("dsn/kinds.jcl") == Job(
        "ACCEPT",
        (
            b.pgm(
                "S1",
                "PGMA",
                (
                    b.dataset("IN", "T.IN"),
                    b.temp("OUT", "WORK", b.disp("NEW", "PASS", "DELETE")),
                    b.in_stream("SYSIN", (" CARD ONE", " CARD TWO")),
                    b.in_stream("DATA1", (" DATA LINE",)),
                    b.dummy("NULL1"),
                    b.dummy("NULL2"),
                    b.sysout("REPORT"),
                ),
            ),
            b.pgm(
                "S2",
                "PGMB",
                (
                    b.backref("COPY", b.ref("S1"), "IN"),
                    b.backref("PCOPY", b.ref_in("S1", "P1"), "IN"),
                ),
            ),
        ),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_lone_symbol_dsn_expands_to_temp(expand_fixture):
    from jackal.expansion import ExpandedJob
    from tests.acceptance import build as b

    s1 = b.qualified(
        (),
        b.pgm("S1", "PGMA", (b.temp("OUT", "WORK", b.disp("NEW", "PASS", "DELETE")),)),
    )
    assert expand_fixture("dsn/temps.jcl") == ExpandedJob(
        "ACCEPT",
        (
            s1,
            b.qualified(
                (),
                b.pgm(
                    "S2",
                    "PGMB",
                    (
                        b.temp("IN", "WORK", b.disp("OLD", "DELETE", "DELETE")),
                        b.resolved_backref("COPY", s1, "OUT"),
                    ),
                ),
            ),
        ),
    )
