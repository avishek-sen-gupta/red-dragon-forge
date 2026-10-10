"""End-to-end proof: expand_procs() against the real CardDemo TRANREPT.jcl,
REPROC.prc, and TRANREPT.prc — not synthetic fixtures. Skips cleanly without
CARDDEMO_HOME (see jackal/tests/conftest.py's carddemo_home fixture)."""

from __future__ import annotations

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.dsn import DdName, DirectDSN
from jackal.expansion import DirectoryProcLibrary, ExpandedJob, expand_or_fail
from jackal.jcl.parser import parse_jcl
from jackal.model import ProcCall, ProcRef, ProgramRef, ProgramStep, StepName
from jackal.value_parts import SymbolName, literal


@pytest.fixture(autouse=True)
def _require_jcl_bridge(jcl_bridge_jar):
    """parse_jcl/parse_proc shell to the bridge; ensure JCL_BRIDGE_JAR is set."""


def _tranrept(carddemo_home) -> ExpandedJob:
    job = parse_jcl((carddemo_home / "jcl" / "TRANREPT.jcl").read_text())
    return expand_or_fail(job, DirectoryProcLibrary((carddemo_home / "proc",)))


def _program(expanded: ExpandedJob, name: str) -> ProgramStep:
    return next(
        q.step
        for q in expanded.steps
        if q.rendered() == name and isinstance(q.step, ProgramStep)
    )


@pytest.mark.carddemo_e2e
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_tranrept_jcl_expands_reproc_call(carddemo_home):
    job = parse_jcl((carddemo_home / "jcl" / "TRANREPT.jcl").read_text())
    call = next(
        s
        for s in job.steps
        if isinstance(s, ProcCall) and s.label == StepName("STEP05R")
    )
    assert (call.proc, call.symbol_overrides) == (
        ProcRef("REPROC"),
        ((SymbolName("CNTLLIB"), literal("AWS.M2.CARDDEMO.CNTL")),),
    )

    expanded = _tranrept(carddemo_home)
    assert _program(expanded, "STEP05R.PRC001").pgm == ProgramRef("IDCAMS")
    assert _program(expanded, "STEP10R").pgm == ProgramRef("CBTRN03C")
    assert [q.step.pgm for q in expanded.steps if q.rendered() == "STEP05R"] == [
        ProgramRef("SORT")
    ]


@pytest.mark.carddemo_e2e
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_tranrept_jcl_dd_overrides_reach_the_real_datasets(carddemo_home):
    prc001 = _program(_tranrept(carddemo_home), "STEP05R.PRC001")
    dsns = {dd.ddname: dd.dsn for dd in prc001.dds}
    assert dsns[DdName("FILEIN")] == DirectDSN(
        literal("AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS")
    )
    assert dsns[DdName("FILEOUT")] != DirectDSN(literal("NULLFILE"))
