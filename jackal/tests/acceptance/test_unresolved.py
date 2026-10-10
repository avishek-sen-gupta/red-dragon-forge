"""Acceptance: a call to a PROC in no library."""

from tests.acceptance.markers import EXPANDED
from tests.covers import NotLanguageFeature, covers


@EXPANDED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_unresolved_proc_expands(expand_fixture):
    from jackal.expansion import ExpandedJob, UnresolvedProcCall
    from jackal.model import ProcCall
    from tests.acceptance import build as b

    assert expand_fixture("unresolved/unresolved.jcl") == ExpandedJob(
        "ACCEPT",
        (
            b.qualified((), b.pgm("S1", "PGMA")),
            b.qualified((), UnresolvedProcCall(ProcCall(b.name("S2"), "NOSUCHP"))),
        ),
    )
