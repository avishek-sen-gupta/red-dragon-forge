"""Integration tests: a new dataset is labelled at allocation from its DD's DCB over its model's label."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from catnip.alternate_index import AlternateIndex
from catnip.catalog_path import CatalogPath
from catnip.labels import KsdsLabel, LabelPending, RecordFormat, SequentialLabel
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.model import (
    DD,
    BackwardRef,
    Dcb,
    DdName,
    DirectDSN,
    NoDSN,
    StepDd,
    StepRef,
    UnresolvedDd,
)
from jackal.results import AllocationError, AllocationFailed, Completed
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy, UnresolvedReference
from jackal.value_parts import literal
from tests.covers import NotLanguageFeature, covers
from tests.package_build import EMPTY
from tests.model_build import dd, disp, job, program, ref
from tests.system_build import job_catalog, scratch, system, upload

_FB80 = SequentialLabel(RecordFormat.FB, 80)


def _runner(tmp_path: Path) -> JobRunner:
    return JobRunner(
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        package=EMPTY,
        system=system(tmp_path),
    )


def _new(ddname: str, dcb: Dcb[StepRef], d: str = "NEW") -> DD[StepRef]:
    return replace(dd(ddname, f"T.{ddname}", disp(d, "CATLG")), dcb=dcb)


def _dcb(model=NoDSN(), recfm: str = "", lrecl: str = "") -> Dcb[StepRef]:
    return Dcb(model, literal(recfm) if recfm else (), literal(lrecl) if lrecl else ())


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_new_dataset_takes_its_label_from_its_dcb_over_its_model(tmp_path):
    """Record A3/A5/A7: the model's label completed by the DD's own RECFM and
    LRECL; FBA labels FB and VBA labels VB; RECFM=U or a missing LRECL leaves the
    label pending; DCB=*.dd and *.step.dd copy that DD's subparameters; an
    existing dataset's label is not changed."""
    upload(tmp_path, "T.MODEL", b"", _FB80)
    upload(tmp_path, "T.OLD", b"", _FB80)
    model = DirectDSN(literal("T.MODEL"))
    j = job(
        "J",
        (
            program(
                "S1",
                "IEFBR14",
                (
                    _new("A", _dcb(model)),
                    _new("B", _dcb(model, lrecl="120")),
                    _new("C", _dcb(recfm="VBA", lrecl="204")),
                    _new("D", _dcb(recfm="FB")),
                    _new("E", _dcb(recfm="U", lrecl="100")),
                    _new("F", _dcb(StepDd(DdName("C")), recfm="VB")),
                    replace(dd("OLD", "T.OLD", disp("SHR")), dcb=_dcb(lrecl="100")),
                ),
            ),
            program(
                "S2",
                "IEFBR14",
                (
                    _new(
                        "G",
                        _dcb(
                            BackwardRef(ref("S1"), UnresolvedDd(DdName("C"))),
                            lrecl="300",
                        ),
                    ),
                ),
            ),
        ),
    )
    result = _runner(tmp_path).run(j, scratch=scratch(tmp_path))
    after = job_catalog(tmp_path)
    assert [s.outcome for s in result.steps] == [Completed(0), Completed(0)]
    assert {n: after.resolve(f"T.{n}").label for n in "ABCDEFG"} | {
        "OLD": after.resolve("T.OLD").label
    } == {
        "A": _FB80,
        "B": SequentialLabel(RecordFormat.FB, 120),
        "C": SequentialLabel(RecordFormat.VB, 204),
        "D": LabelPending(),
        "E": LabelPending(),
        "F": SequentialLabel(RecordFormat.VB, 204),
        "G": SequentialLabel(RecordFormat.VB, 300),
        "OLD": _FB80,
    }


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_model_that_is_not_cataloged_fails_the_allocation(tmp_path):
    """Record A6, JCL Ref p. 128: DCB=dsname names a cataloged data set."""
    j = job(
        "J",
        (program("S1", "IEFBR14", (_new("A", _dcb(DirectDSN(literal("T.NOPE")))),)),),
    )
    result = _runner(tmp_path).run(j, scratch=scratch(tmp_path))
    assert result.steps[0].outcome == AllocationFailed(
        DdName("A"), AllocationError.DATASET_NOT_FOUND
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_like_copies_a_cataloged_model_and_refdd_copies_a_dds_coded_attributes(
    tmp_path,
):
    """JCL Ref pp. 208-210: LIKE=dsname copies a cataloged model's RECORG or
    RECFM and LRECL, a KSDS's included, and LRECL or RECFM coded on the DD
    override them; a path is copied as its base cluster; a model not cataloged fails the allocation. pp. 238-240:
    REFDD=*.ddname or *.step.ddname copies the RECFM and LRECL coded on that DD,
    never its dataset's label. A REFDD or DCB referback naming no earlier DD is an
    unresolved reference, rejected before any step runs."""
    upload(tmp_path, "T.MODEL", b"", _FB80)
    upload(tmp_path, "T.KSDS", b"", KsdsLabel(100, 0, 8))
    system(tmp_path).define_aix(AlternateIndex("T.AIX", "T.KSDS", 8, 4, False))
    system(tmp_path).define_path(CatalogPath("T.PATH", "T.AIX"))
    model, ksds = DirectDSN(literal("T.MODEL")), DirectDSN(literal("T.KSDS"))
    through = DirectDSN(literal("T.PATH"))
    c_in_s1 = BackwardRef(ref("S1"), UnresolvedDd(DdName("C")))
    l1_in_s1 = BackwardRef(ref("S1"), UnresolvedDd(DdName("L1")))
    j = job(
        "J",
        (
            program(
                "S1",
                "IEFBR14",
                (
                    _new("C", _dcb(recfm="VB", lrecl="204")),
                    _new("L1", replace(_dcb(), like=model)),
                    _new("L2", replace(_dcb(lrecl="120"), like=model)),
                    _new("L3", replace(_dcb(), like=ksds)),
                    _new("L4", replace(_dcb(lrecl="200"), like=ksds)),
                    _new("L5", replace(_dcb(recfm="VB", lrecl="84"), like=ksds)),
                    _new("L6", replace(_dcb(), like=through)),
                    _new("R1", replace(_dcb(), refdd=StepDd(DdName("C")))),
                ),
            ),
            program(
                "S2",
                "IEFBR14",
                (
                    _new("R2", replace(_dcb(lrecl="300"), refdd=c_in_s1)),
                    _new("R3", replace(_dcb(), refdd=l1_in_s1)),
                ),
            ),
        ),
    )
    missing = job(
        "M",
        (
            program(
                "S1",
                "IEFBR14",
                (_new("X", replace(_dcb(), like=DirectDSN(literal("T.NOPE")))),),
            ),
        ),
    )
    result = _runner(tmp_path).run(j, scratch=scratch(tmp_path))
    failed = _runner(tmp_path).run(missing, scratch=scratch(tmp_path))
    after = job_catalog(tmp_path)
    assert [s.outcome for s in result.steps] == [Completed(0), Completed(0)]
    assert {
        n: after.resolve(f"T.{n}").label
        for n in ("L1", "L2", "L3", "L4", "L5", "L6", "R1", "R2", "R3")
    } == {
        "L1": _FB80,
        "L2": SequentialLabel(RecordFormat.FB, 120),
        "L3": KsdsLabel(100, 0, 8),
        "L4": KsdsLabel(200, 0, 8),
        "L5": SequentialLabel(RecordFormat.VB, 84),
        "L6": KsdsLabel(100, 0, 8),
        "R1": SequentialLabel(RecordFormat.VB, 204),
        "R2": SequentialLabel(RecordFormat.VB, 300),
        "R3": LabelPending(),
    }
    assert failed.steps[0].outcome == AllocationFailed(
        DdName("X"), AllocationError.DATASET_NOT_FOUND
    )
    for dangling in (
        replace(_dcb(), refdd=StepDd(DdName("NOPE"))),
        _dcb(BackwardRef(ref("S9"), UnresolvedDd(DdName("X")))),
    ):
        with pytest.raises(UnresolvedReference):
            _runner(tmp_path).run(
                job("D", (program("S1", "IEFBR14", (_new("Y", dangling),)),)),
                scratch=scratch(tmp_path),
            )
