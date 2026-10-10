"""Acceptance: each JclError variant."""

from tests.acceptance.markers import EXPANDED
from tests.covers import NotLanguageFeature, covers


@EXPANDED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_jcl_errors_expand(expand_fixture, parse_fixture):
    from jackal.expansion import (
        CircularProc,
        DanglingDdReference,
        DanglingReference,
        ErrorSite,
        ForwardReference,
        OverrideNamesNoStep,
        ReferenceToProcCall,
    )
    from tests.acceptance import build as b

    def step(rel: str, index: int) -> object:
        return parse_fixture(rel).steps[index]

    assert [
        expand_fixture("errors/dangling.jcl"),
        expand_fixture("errors/dangling_dd.jcl"),
        expand_fixture("errors/forward.jcl"),
        expand_fixture("errors/proc_call.jcl"),
        expand_fixture("errors/no_step.jcl"),
        expand_fixture("errors/circular.jcl"),
    ] == [
        DanglingReference(ErrorSite((), step("errors/dangling.jcl", 1)), b.ref("NOPE")),
        DanglingDdReference(
            ErrorSite((), step("errors/dangling_dd.jcl", 1)), b.ref("S1"), "NOPE"
        ),
        ForwardReference(ErrorSite((), step("errors/forward.jcl", 0)), b.ref("S2")),
        ReferenceToProcCall(
            ErrorSite((), step("errors/proc_call.jcl", 1)), b.ref("S1")
        ),
        OverrideNamesNoStep(step("errors/no_step.jcl", 0), b.name("P9")),
        CircularProc(("CIRCA", "CIRCB", "CIRCA")),
    ]
