"""Acceptance: EXEC statements, labels and PARM text."""

from tests.acceptance.markers import EXPANDED, PARSED
from tests.covers import NotLanguageFeature, covers


@PARSED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_steps_parse(parse_fixture):
    from jackal.model import Job, ProcCall
    from tests.acceptance import build as b

    assert parse_fixture("steps/labels.jcl") == Job(
        "ACCEPT",
        (
            b.pgm("S1", "PGMA", parm="A=(,255)"),
            ProcCall(b.name("S2"), "MYP"),
            ProcCall(b.name("S3"), "MYP"),
            b.pgm("", "PGMB", parm="X (Y"),
            b.pgm("S5", "PGMC", parm="PLAIN"),
        ),
    )


@EXPANDED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_steps_expand(expand_fixture):
    from jackal.expansion import ExpandedJob
    from jackal.model import ProcCall
    from tests.acceptance import build as b

    s2 = ProcCall(b.name("S2"), "MYP")
    s3 = ProcCall(b.name("S3"), "MYP")
    assert expand_fixture("steps/labels.jcl") == ExpandedJob(
        "ACCEPT",
        (
            b.qualified((), b.pgm("S1", "PGMA", parm="A=(,255)")),
            b.qualified((s2,), b.pgm("P1", "PGMP")),
            b.qualified((s3,), b.pgm("P1", "PGMP")),
            b.qualified((), b.pgm("", "PGMB", parm="X (Y")),
            b.qualified((), b.pgm("S5", "PGMC", parm="PLAIN")),
        ),
    )
