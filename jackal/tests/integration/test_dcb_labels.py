"""Integration tests: a new dataset is labelled at allocation from its DD's DCB over its model's label."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.labels import LabelPending, RecordFormat, SequentialLabel
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
from jackal.unresolved import RaiseErrorStrategy
from jackal.value_parts import literal
from tests.covers import NotLanguageFeature, covers
from tests.model_build import dd, disp, job, program, ref
from tests.system_build import job_catalog, scratch, system, upload

_FB80 = SequentialLabel(RecordFormat.FB, 80)


def _runner(tmp_path: Path) -> JobRunner:
    return JobRunner(
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        source_dir=tmp_path,
        bridge_jar="unused",
        system=system(tmp_path),
        copybook_dir=tmp_path,
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
