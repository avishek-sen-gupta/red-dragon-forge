import pytest
from tests.covers import NotLanguageFeature, covers
from tests.wire_build import (
    cond_test,
    dd,
    job_json,
    name_dsn,
    program,
)
from jackal.dsn import (
    BackwardRef,
    DirectDSN,
    DummyDSN,
    InStreamDSN,
    NoDSN,
    TempRef,
)
from jackal.jcl import wire
from jackal.jcl.bridge_parser import JclParseError, job_from_bridge_json
from jackal.model import Cond, CondOp, DispNormal, DispStatus
from jackal.value_parts import literal


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserialize_job_steps_dds():
    out = job_json(
        "PIPE",
        (
            program(
                "STEP1",
                "UPCASE",
                (
                    dd("INDD", name_dsn("J.IN"), ("SHR",)),
                    dd("WORKDD", name_dsn("J.WORK"), ("NEW", "PASS", "DELETE")),
                ),
            ),
            program("STEP2", "STARRER"),
        ),
    )
    job = job_from_bridge_json(out)
    assert job.name == "PIPE"
    assert [s.name for s in job.steps] == ["STEP1", "STEP2"]
    assert [s.pgm for s in job.steps] == ["UPCASE", "STARRER"]
    w = job.steps[0].dds[1]
    assert (w.disp.status, w.disp.normal, w.disp.abnormal) == (
        DispStatus.NEW,
        DispNormal.PASS,
        DispNormal.DELETE,
    )
    d = job.steps[0].dds[0]
    assert (d.disp.status, d.disp.normal, d.disp.abnormal) == (
        DispStatus.SHR,
        DispNormal.KEEP,
        DispNormal.KEEP,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserialize_each_dsn_kind():
    out = job_json(
        "J",
        (
            program(
                "S",
                "IDCAMS",
                (
                    dd(
                        "SYSIN",
                        wire.InStreamDsn(),
                        in_stream=("   DELETE A.B CLUSTER",),
                    ),
                    dd("SYSPRINT", sysout=True),
                    dd("WRK", wire.TempDsn(name="WORKIN"), ("NEW", "PASS")),
                    dd("IN", name_dsn("MY.DATA"), ("SHR",)),
                    dd("NULL", wire.DummyDsn()),
                    dd(
                        "INPUT",
                        wire.BackrefDsn(
                            target=wire.StepTarget(step="STEP1"), ddname="WRK"
                        ),
                        ("OLD", "DELETE"),
                    ),
                ),
            ),
        ),
    )
    dds = job_from_bridge_json(out).steps[0].dds
    assert [(d.ddname, d.dsn, d.in_stream, d.sysout) for d in dds] == [
        ("SYSIN", InStreamDSN(), ("   DELETE A.B CLUSTER",), False),
        ("SYSPRINT", NoDSN(), (), True),
        ("WRK", TempRef("&&WORKIN"), (), False),
        ("IN", DirectDSN(literal("MY.DATA")), (), False),
        ("NULL", DummyDSN(), (), False),
        ("INPUT", BackwardRef(step="STEP1", ddname="WRK"), (), False),
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserialize_step_and_job_cond():
    out = job_json(
        "J",
        (
            program(
                "S",
                "P",
                cond=wire.Cond(tests=(cond_test(4, "LT", "A"),), mode="NORMAL"),
            ),
            program("T", "P"),
        ),
        end_job_tests=(wire.RcComparison(code=0, op="NE"),),
    )
    job = job_from_bridge_json(out)
    assert job.cond == (Cond(0, CondOp.NE),)
    assert [s.conds for s in job.steps] == [(Cond(4, CondOp.LT, "A"),), ()]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserialize_shapes_the_old_model_cannot_hold_fail_loud():
    even = job_json("J", (program("S", "P", cond=wire.Cond(tests=(), mode="EVEN")),))
    three_segment = job_json(
        "J",
        (
            program(
                "S",
                "P",
                (
                    dd(
                        "INPUT",
                        wire.BackrefDsn(
                            target=wire.ProcStepTarget(call="STEP1", step="PSTEP"),
                            ddname="WRK",
                        ),
                    ),
                ),
            ),
        ),
    )
    with pytest.raises(JclParseError, match="jackal-1o2.8"):
        job_from_bridge_json(even)
    with pytest.raises(JclParseError, match="jackal-lz8"):
        job_from_bridge_json(three_segment)
