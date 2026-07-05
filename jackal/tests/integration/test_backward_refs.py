"""Integration tests: DSN=*.STEP.DD backward reference resolution via JobRunner."""

from __future__ import annotations

from jackal.dsn import DirectDSN, TempRef
from jackal.model import DD, Disp, DispNormal, DispStatus, Job, Step
from jackal.results import StepDisposition
from jackal.runner import JobRunner
from tests.covers import NotLanguageFeature, covers


def _runner(tmp_path):
    return JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_backward_ref_resolves_to_prior_step_dataset(tmp_path):
    """Step 2 DD with BackwardRef to step 1's WRK resolves to the same DirectDSN."""
    from jackal.dsn import BackwardRef

    job = Job(
        name="J",
        steps=(
            Step(
                name="STEP1",
                pgm="IEFBR14",
                dds=(
                    DD(
                        "WRK",
                        DirectDSN("MY.FILE"),
                        Disp(DispStatus.NEW, DispNormal.PASS, DispNormal.DELETE),
                    ),
                ),
            ),
            Step(
                name="STEP2",
                pgm="IEFBR14",
                dds=(
                    DD(
                        "INPUT",
                        BackwardRef("STEP1", "WRK"),
                        Disp(DispStatus.OLD, DispNormal.DELETE, DispNormal.DELETE),
                    ),
                ),
            ),
        ),
    )
    (tmp_path / "myfile").write_bytes(b"")
    result = _runner(tmp_path).run(
        job, workdir=tmp_path, seeds={"MY.FILE": tmp_path / "myfile"}
    )
    assert all(s.ran and s.return_code == 0 for s in result.steps)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_backward_ref_to_bypassed_step_also_bypasses(tmp_path):
    """If step 1 is bypassed, step 2 referencing *.STEP1.WRK is also bypassed.

    STEP0 runs first (RC=0).  STEP1 has COND=(0,GE) so it is bypassed
    (0 >= 0 is true for STEP0's RC).  STEP2 back-references STEP1's WRK DD;
    because STEP1 never ran it is absent from resolved_dds, so STEP2 is also
    bypassed via the IBM backward-ref bypass rule.
    """
    from jackal.dsn import BackwardRef
    from jackal.model import Cond, CondOp

    job = Job(
        name="J",
        steps=(
            Step(
                name="STEP0",
                pgm="IEFBR14",
                dds=(),
            ),
            Step(
                name="STEP1",
                pgm="IEFBR14",
                dds=(
                    DD(
                        "WRK",
                        DirectDSN("MY.FILE"),
                        Disp(DispStatus.NEW, DispNormal.PASS, DispNormal.DELETE),
                    ),
                ),
                conds=(Cond(code=0, op=CondOp.GE),),  # 0 >= STEP0 RC(0) → bypass
            ),
            Step(
                name="STEP2",
                pgm="IEFBR14",
                dds=(
                    DD(
                        "INPUT",
                        BackwardRef("STEP1", "WRK"),
                        Disp(DispStatus.OLD, DispNormal.DELETE, DispNormal.DELETE),
                    ),
                ),
            ),
        ),
    )
    result = _runner(tmp_path).run(job, workdir=tmp_path, seeds={})
    _step0, step1, step2 = result.steps
    assert step1.disposition is StepDisposition.BYPASSED
    assert step2.disposition is StepDisposition.BYPASSED
    assert step2.ran is False
