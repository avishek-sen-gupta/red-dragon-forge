"""Unit tests for expand_procs()."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.dsn import DirectDSN
from jackal.jcl.proc_expand import ProcExpansionError, expand_procs
from jackal.model import DD, Cond, CondOp, Disp, DispNormal, DispStatus, Job, Step
from jackal.value_parts import Literal, Symbol, literal

_FIXTURES = Path(__file__).parent / "fixtures" / "proc"
_DEFAULT_DISP = Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP)


@pytest.fixture(autouse=True)
def _require_jcl_bridge(jcl_bridge_jar):
    """expand_procs parses referenced .prc files via parse_proc; ensure JCL_BRIDGE_JAR is set."""


def _step(name: str, pgm: str, dds: tuple[DD, ...] = (), proc_parms=None) -> Step:
    return Step(name=name, pgm=pgm, dds=dds, proc_parms=proc_parms or {})


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_non_proc_step_passes_through_unchanged():
    step = _step("STEP1", "IEFBR14")
    job = Job(name="J", steps=(step,))
    result = expand_procs(job, proclib_dirs=[_FIXTURES])
    assert result.steps == (step,)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_proc_call_expands_to_qualified_inner_step():
    step = _step(
        "STEP05R", "REPROC", proc_parms={"CNTLLIB": literal("AWS.M2.CARDDEMO.CNTL")}
    )
    job = Job(name="TRANREPT", steps=(step,))
    result = expand_procs(job, proclib_dirs=[_FIXTURES])
    assert [s.name for s in result.steps] == ["STEP05R.PRC001"]
    assert result.steps[0].pgm == "IDCAMS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_proc_symbol_substituted_from_caller_override():
    step = _step(
        "STEP05R", "REPROC", proc_parms={"CNTLLIB": literal("AWS.M2.CARDDEMO.CNTL")}
    )
    job = Job(name="TRANREPT", steps=(step,))
    result = expand_procs(job, proclib_dirs=[_FIXTURES])
    sysin = next(d for d in result.steps[0].dds if d.ddname == "SYSIN")
    assert sysin.dsn == DirectDSN(
        (Literal("AWS.M2.CARDDEMO.CNTL"), Literal("(REPROCT)"))
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_missing_symbol_raises():
    step = _step(
        "STEP05R", "REPROC"
    )  # no CNTLLIB override, REPROC.prc has no default either
    job = Job(name="TRANREPT", steps=(step,))
    with pytest.raises(ProcExpansionError, match="CNTLLIB"):
        expand_procs(job, proclib_dirs=[_FIXTURES])


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dd_qualified_override_replaces_placeholder():
    outer_dd = DD(
        ddname="PRC001.FILEIN",
        dsn=DirectDSN(literal("AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS")),
        disp=_DEFAULT_DISP,
    )
    step = _step(
        "STEP05R",
        "REPROC",
        dds=(outer_dd,),
        proc_parms={"CNTLLIB": literal("AWS.M2.CARDDEMO.CNTL")},
    )
    job = Job(name="TRANREPT", steps=(step,))
    result = expand_procs(job, proclib_dirs=[_FIXTURES])
    filein = next(d for d in result.steps[0].dds if d.ddname == "FILEIN")
    assert filein.dsn == DirectDSN(literal("AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dd_qualified_override_unmatched_step_name_is_not_applied():
    # A qualified override for a step name the PROC doesn't have is simply
    # never matched — it stays on the outer step's own dds, unconsumed.
    outer_dd = DD(
        ddname="NOPE.FILEIN",
        dsn=DirectDSN(literal("SOME.DATASET")),
        disp=_DEFAULT_DISP,
    )
    step = _step(
        "STEP05R",
        "REPROC",
        dds=(outer_dd,),
        proc_parms={"CNTLLIB": literal("AWS.M2.CARDDEMO.CNTL")},
    )
    job = Job(name="TRANREPT", steps=(step,))
    result = expand_procs(job, proclib_dirs=[_FIXTURES])
    filein = next(d for d in result.steps[0].dds if d.ddname == "FILEIN")
    assert filein.dsn == DirectDSN(literal("NULLFILE"))  # unchanged placeholder


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_nested_proc_call_expands_recursively():
    step = _step("STEP01R", "CALLER")
    job = Job(name="OUTER", steps=(step,))
    result = expand_procs(job, proclib_dirs=[_FIXTURES])
    # CALLER.prc's own STEP01R calls REPROC with CNTLLIB=AWS.M2.CARDDEMO.CNTL
    assert [s.name for s in result.steps] == ["STEP01R.STEP01R.PRC001"]
    assert result.steps[0].pgm == "IDCAMS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_circular_proc_reference_raises(tmp_path):
    (tmp_path / "SELFCALL.prc").write_text(
        "//SELFCALL PROC\n//S1 EXEC PROC=SELFCALL\n// PEND\n"
    )
    step = _step("STEP1", "SELFCALL")
    job = Job(name="J", steps=(step,))
    with pytest.raises(ProcExpansionError, match="Circular"):
        expand_procs(job, proclib_dirs=[tmp_path])


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_job_steps_flatten_in_order_around_a_proc_call():
    before = _step("STEP01", "IEFBR14")
    proc_call = _step("STEP05R", "REPROC", proc_parms={"CNTLLIB": literal("X")})
    after = _step("STEP10", "IEFBR14")
    job = Job(name="J", steps=(before, proc_call, after))
    result = expand_procs(job, proclib_dirs=[_FIXTURES])
    assert [s.name for s in result.steps] == ["STEP01", "STEP05R.PRC001", "STEP10"]
