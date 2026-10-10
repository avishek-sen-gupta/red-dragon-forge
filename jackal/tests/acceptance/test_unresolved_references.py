"""Acceptance: a reference that cannot be resolved expands, with each coordinate saying what was found."""

import logging
from dataclasses import replace

from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_name_that_matches_nothing_is_an_unresolved_coordinate(
    expand_fixture, parse_fixture, caplog
):
    from jackal.expansion import ExpandedJob
    from jackal.model import (
        BackwardRef,
        StepReference,
        UnresolvedDd,
        UnresolvedProgramStep,
    )
    from tests.acceptance import build as b

    with caplog.at_level(logging.WARNING, logger="jackal.expansion"):
        dangling = expand_fixture("errors/dangling.jcl")
        dangling_dd = expand_fixture("errors/dangling_dd.jcl")
    nope = StepReference((), UnresolvedProgramStep(b.name("NOPE")))
    s1 = b.qualified((), b.pgm("S1", "PGMA"))
    s1_in = b.qualified((), b.pgm("S1", "PGMA", (b.dataset("IN", "T.IN"),)))
    copy = b.DD(
        b.dd_name("COPY"),
        BackwardRef(s1_in.reference(), UnresolvedDd(b.dd_name("NOPE"))),
        b.SHR,
    )
    assert (dangling, dangling_dd) == (
        ExpandedJob(
            "ACCEPT",
            (
                s1,
                b.qualified(
                    (), b.pgm("S2", "PGMB", condition=b.cond(b.on_step(4, "LT", nope)))
                ),
            ),
        ),
        ExpandedJob("ACCEPT", (s1_in, b.qualified((), b.pgm("S2", "PGMB", (copy,))))),
    )
    assert [r.getMessage() for r in caplog.records] == [
        "S2 refers to NOPE, which is not resolved (blueprint D6)",
        "S2 refers to DD NOPE of S1, which has no such DD (blueprint D6)",
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_step_inside_a_proc_in_no_library_is_unresolved_under_a_resolved_call(
    expand_fixture, parse_fixture, caplog
):
    from jackal.expansion import ExpandedJob
    from jackal.model import (
        CondOp,
        RcTest,
        ResolvedProcCall,
        StepReference,
        UnresolvedProc,
        UnresolvedProgramStep,
    )
    from tests.acceptance import build as b

    def expected(rel: str, inner: str) -> ExpandedJob:
        parsed = parse_fixture(rel).steps
        call, block = parsed[0], parsed[1]
        coordinate = ResolvedProcCall(call, UnresolvedProc(call.proc))
        guard = RcTest(
            StepReference((coordinate,), UnresolvedProgramStep(b.name(inner))),
            CondOp.EQ,
            0,
        )
        return ExpandedJob(
            "ACCEPT",
            (
                b.unexpanded((coordinate,)),
                b.qualified((), replace(block.then[0], guard=guard)),
            ),
        )

    with caplog.at_level(logging.WARNING, logger="jackal.expansion"):
        missing = expand_fixture("unresolved_refs/into_missing_proc.jcl")
        shared = expand_fixture("unresolved_refs/proc_and_step_share_a_name.jcl")
    assert (missing, shared) == (
        expected("unresolved_refs/into_missing_proc.jcl", "S1A"),
        expected("unresolved_refs/proc_and_step_share_a_name.jcl", "P1"),
    )
    assert [r.getMessage() for r in caplog.records] == [
        "S2 refers to S1.S1A, which is not resolved (blueprint D6)",
        "S2 refers to S1.P1, which is not resolved (blueprint D6)",
    ]
