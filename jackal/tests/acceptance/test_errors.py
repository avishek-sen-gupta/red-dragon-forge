"""Acceptance: each JclError variant, all of them mistakes in the JCL itself."""

from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_jcl_errors_expand(expand_fixture, parse_fixture):
    from jackal.expansion import (
        CircularProc,
        ErrorSite,
        ForwardReference,
        OverrideNamesNoStep,
        PathThroughProgramStep,
        ReferenceToProcCall,
    )
    from tests.acceptance import build as b

    def step(rel: str, index: int) -> object:
        return parse_fixture(rel).steps[index]

    assert [
        expand_fixture("errors/forward.jcl"),
        expand_fixture("errors/proc_call.jcl"),
        expand_fixture("errors/through_program.jcl"),
        expand_fixture("errors/no_step.jcl"),
        expand_fixture("errors/circular.jcl"),
    ] == [
        ForwardReference(ErrorSite((), step("errors/forward.jcl", 0)), b.ref("S2")),
        ReferenceToProcCall(
            ErrorSite((), step("errors/proc_call.jcl", 1)), b.ref("S1")
        ),
        PathThroughProgramStep(
            ErrorSite((), step("errors/through_program.jcl", 1)), b.ref_in("S1", "P1")
        ),
        OverrideNamesNoStep(step("errors/no_step.jcl", 0), b.name("P9")),
        CircularProc((b.proc("CIRCA"), b.proc("CIRCB"), b.proc("CIRCA"))),
    ]
