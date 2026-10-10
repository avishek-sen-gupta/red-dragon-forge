"""Acceptance: nested PROCs, an override inside the intermediate PROC, 15 levels."""

from pathlib import Path

from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_nested_procs_expand(expand_fixture):
    from jackal.expansion import ExpandedJob
    from jackal.model import ProcCall, ProcStepOverrides
    from jackal.value_parts import literal
    from tests.acceptance import build as b

    s1 = ProcCall(b.name("S1"), b.proc("OUTER"))
    p1 = ProcCall(
        b.name("P1"),
        b.proc("INNER"),
        per_step=((b.name("Q1"), ProcStepOverrides(parm=literal("SET"))),),
    )
    outer = b.called(s1, "nesting/OUTER.prc")
    inner = b.called(p1, "nesting/INNER.prc")
    assert expand_fixture("nesting/nesting.jcl") == ExpandedJob(
        "ACCEPT",
        (
            b.qualified((outer, inner), b.pgm("Q1", "PGMQ", parm="SET")),
            b.qualified((outer,), b.pgm("P2", "PGMB")),
        ),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_calls_cond_reaches_every_level_of_nesting(expand_fixture, parse_fixture):
    from jackal.expansion import ExpandedJob
    from jackal.model import ProcCall
    from tests.acceptance import build as b

    s1, s2 = parse_fixture("nesting/cond.jcl").steps
    p1 = ProcCall(
        b.name("P1"), b.proc("INNERC"), cond_for_every_step=b.cond(b.all_prior(0, "NE"))
    )
    outer = b.cond(b.all_prior(4, "LT"))
    own = b.cond(b.all_prior(0, "NE"))

    def run(call: object, q: object, p2: object) -> tuple[object, ...]:
        o, i = b.called(call, "nesting/OUTERC.prc"), b.called(p1, "nesting/INNERC.prc")
        return (
            b.qualified((o, i), b.pgm("Q1", "PGMQ", condition=q)),
            b.qualified((o, i), b.pgm("Q2", "PGMR", condition=q)),
            b.qualified((o,), b.pgm("P2", "PGMB", condition=p2)),
        )

    assert expand_fixture("nesting/cond.jcl") == ExpandedJob(
        "ACCEPT", (*run(s1, outer, outer), *run(s2, own, b.NO_COND))
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_fifteen_levels_expand(tmp_path: Path, jcl_bridge_jar: str):
    from jackal.expansion import DirectoryProcLibrary, ExpandedJob, expand_procs
    from jackal.jcl.parser import parse_jcl, parse_proc
    from jackal.model import ProcCall, ResolvedProc, ResolvedProcCall
    from tests.acceptance import build as b

    for level in range(1, 15):
        (tmp_path / f"L{level}.prc").write_text(
            f"//L{level}       PROC\n//C{level}       EXEC L{level + 1}\n"
        )
    (tmp_path / "L15.prc").write_text("//L15      PROC\n//DEEP     EXEC PGM=PGMD\n")
    job = parse_jcl("//ACCEPT   JOB (A),'ACCEPT',CLASS=A\n//S1       EXEC L1\n")
    calls = (ProcCall(b.name("S1"), b.proc("L1")),) + tuple(
        ProcCall(b.name(f"C{level}"), b.proc(f"L{level + 1}")) for level in range(1, 15)
    )
    coordinates = tuple(
        ResolvedProcCall(
            call,
            ResolvedProc(parse_proc((tmp_path / f"{call.proc.name}.prc").read_text())),
        )
        for call in calls
    )
    assert expand_procs(job, DirectoryProcLibrary((tmp_path,))) == ExpandedJob(
        "ACCEPT", (b.qualified(coordinates, b.pgm("DEEP", "PGMD")),)
    )
