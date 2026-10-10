"""Acceptance: nested PROCs, an override inside the intermediate PROC, 15 levels."""

from pathlib import Path

from tests.acceptance.markers import EXPANDED
from tests.covers import NotLanguageFeature, covers


@EXPANDED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_nested_procs_expand(expand_fixture):
    from jackal.expansion import ExpandedJob
    from jackal.model import ProcCall, ProcStepOverrides
    from jackal.value_parts import literal
    from tests.acceptance import build as b

    s1 = ProcCall(b.name("S1"), "OUTER")
    p1 = ProcCall(
        b.name("P1"),
        "INNER",
        per_step=((b.name("Q1"), ProcStepOverrides(parm=literal("SET"))),),
    )
    assert expand_fixture("nesting/nesting.jcl") == ExpandedJob(
        "ACCEPT",
        (
            b.qualified((s1, p1), b.pgm("Q1", "PGMQ", parm="SET")),
            b.qualified((s1,), b.pgm("P2", "PGMB")),
        ),
    )


@EXPANDED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_fifteen_levels_expand(tmp_path: Path, jcl_bridge_jar: str):
    from jackal.expansion import DirectoryProcLibrary, ExpandedJob, expand_procs
    from jackal.jcl.parser import parse_jcl
    from jackal.model import ProcCall
    from tests.acceptance import build as b

    for level in range(1, 15):
        (tmp_path / f"L{level}.prc").write_text(
            f"//L{level}       PROC\n//C{level}       EXEC L{level + 1}\n"
        )
    (tmp_path / "L15.prc").write_text("//L15      PROC\n//DEEP     EXEC PGM=PGMD\n")
    job = parse_jcl("//ACCEPT   JOB (A),'ACCEPT',CLASS=A\n//S1       EXEC L1\n")
    calls = (ProcCall(b.name("S1"), "L1"),) + tuple(
        ProcCall(b.name(f"C{level}"), f"L{level + 1}") for level in range(1, 15)
    )
    assert expand_procs(job, DirectoryProcLibrary((tmp_path,))) == ExpandedJob(
        "ACCEPT", (b.qualified(calls, b.pgm("DEEP", "PGMD")),)
    )
