"""Acceptance: a call to a PROC in no library."""

from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_unresolved_proc_expands(expand_fixture):
    from jackal.expansion import ExpandedJob
    from jackal.model import ProcCall, ResolvedProcCall, UnresolvedProc
    from tests.acceptance import build as b

    assert expand_fixture("unresolved/unresolved.jcl") == ExpandedJob(
        "ACCEPT",
        (
            b.qualified((), b.pgm("S1", "PGMA")),
            b.unexpanded(
                (
                    ResolvedProcCall(
                        ProcCall(b.name("S2"), b.proc("NOSUCHP")),
                        UnresolvedProc(b.proc("NOSUCHP")),
                    ),
                )
            ),
        ),
    )
