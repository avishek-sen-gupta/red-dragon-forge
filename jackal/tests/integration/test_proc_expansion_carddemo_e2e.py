"""End-to-end proof: expand_procs() against the real CardDemo TRANREPT.jcl,
REPROC.prc, and TRANREPT.prc — not synthetic fixtures. Skips cleanly without
CARDDEMO_HOME (see jackal/tests/conftest.py's carddemo_home fixture)."""

from __future__ import annotations

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.dsn import DirectDSN
from jackal.jcl.parser import parse_jcl
from jackal.jcl.proc_expand import expand_procs
from jackal.value_parts import literal


@pytest.fixture(autouse=True)
def _require_jcl_bridge(jcl_bridge_jar):
    """parse_jcl/parse_proc shell to the bridge; ensure JCL_BRIDGE_JAR is set."""


@pytest.mark.carddemo_e2e
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_tranrept_jcl_expands_reproc_call(carddemo_home):
    jcl_text = (carddemo_home / "jcl" / "TRANREPT.jcl").read_text()
    job = parse_jcl(jcl_text)

    # Before expansion: STEP05R's pgm is literally "REPROC" (the bug this
    # feature fixes — a graph/runner consumer would treat REPROC as if it
    # were a real executable).
    step05r = next(s for s in job.steps if s.name == "STEP05R")
    assert step05r.pgm == "REPROC"
    assert step05r.proc_parms == {"CNTLLIB": literal("AWS.M2.CARDDEMO.CNTL")}

    expanded = expand_procs(job, proclib_dirs=[carddemo_home / "proc"])

    # After expansion: the PROC-call step is gone, replaced by its real
    # qualified inner step running the real program (IDCAMS). No step's pgm
    # is the bare literal "REPROC" any more (the exact bug this feature
    # fixes: a graph/runner consumer treating REPROC as a real executable).
    #
    # Note: real TRANREPT.jcl reuses the literal step name "STEP05R" twice —
    # once for `EXEC PROC=REPROC` (the call this feature expands) and,
    # entirely unrelated, again for a later plain `EXEC PGM=SORT` step. That
    # second STEP05R is not a PROC call and must be left untouched by
    # expand_procs, so "STEP05R" legitimately still appears in `names`
    # afterwards — it just no longer has pgm == "REPROC".
    names = [s.name for s in expanded.steps]
    assert "STEP05R.PRC001" in names
    assert "STEP10R" in names
    assert all(s.pgm != "REPROC" for s in expanded.steps)

    prc001 = next(s for s in expanded.steps if s.name == "STEP05R.PRC001")
    assert prc001.pgm == "IDCAMS"

    sort_step = next(
        s for s in expanded.steps if s.name == "STEP05R" and s.pgm == "SORT"
    )
    assert sort_step.pgm == "SORT"

    step10r = next(s for s in expanded.steps if s.name == "STEP10R")
    assert step10r.pgm == "CBTRN03C"


@pytest.mark.carddemo_e2e
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_tranrept_jcl_dd_overrides_reach_the_real_datasets(carddemo_home):
    jcl_text = (carddemo_home / "jcl" / "TRANREPT.jcl").read_text()
    job = parse_jcl(jcl_text)
    expanded = expand_procs(job, proclib_dirs=[carddemo_home / "proc"])

    prc001 = next(s for s in expanded.steps if s.name == "STEP05R.PRC001")
    filein = next(d for d in prc001.dds if d.ddname == "FILEIN")
    fileout = next(d for d in prc001.dds if d.ddname == "FILEOUT")

    # These come from TRANREPT.jcl's own //PRC001.FILEIN / //PRC001.FILEOUT
    # qualified DD overrides — replacing REPROC.prc's own NULLFILE
    # placeholders, proving the override mechanism against real JCL text.
    assert filein.dsn == DirectDSN(literal("AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS"))
    assert fileout.dsn != DirectDSN(literal("NULLFILE"))
