import pytest
from tests.covers import NotLanguageFeature, covers
from jackal.jcl.bridge_parser import _job_from_json
from jackal.model import CondOp, DispNormal, DispStatus


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserialize_job_steps_dds():
    data = {
        "name": "PIPE",
        "steps": [
            {
                "name": "STEP1",
                "pgm": "UPCASE",
                "dds": [
                    {
                        "ddname": "INDD",
                        "dsn": "J.IN",
                        "disp_words": ["SHR"],
                        "in_stream": [],
                        "sysout": False,
                    },
                    {
                        "ddname": "WORKDD",
                        "dsn": "J.WORK",
                        "disp_words": ["NEW", "PASS", "DELETE"],
                        "in_stream": [],
                        "sysout": False,
                    },
                ],
            },
            {"name": "STEP2", "pgm": "STARRER", "dds": []},
        ],
    }
    job = _job_from_json(data)
    assert job.name == "PIPE"
    assert [s.name for s in job.steps] == ["STEP1", "STEP2"]
    assert [s.pgm for s in job.steps] == ["UPCASE", "STARRER"]
    w = job.steps[0].dds[1]
    assert (w.disp.status, w.disp.normal, w.disp.abnormal) == (
        DispStatus.NEW,
        DispNormal.PASS,
        DispNormal.DELETE,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserialize_disp_shr_defaults_keep_keep():
    data = {
        "name": "J",
        "steps": [
            {
                "name": "S",
                "pgm": "P",
                "dds": [
                    {
                        "ddname": "D",
                        "dsn": "A.B",
                        "disp_words": ["SHR"],
                        "in_stream": [],
                        "sysout": False,
                    }
                ],
            }
        ],
    }
    d = _job_from_json(data).steps[0].dds[0]
    assert (d.disp.status, d.disp.normal, d.disp.abnormal) == (
        DispStatus.SHR,
        DispNormal.KEEP,
        DispNormal.KEEP,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserialize_instream_and_sysout():
    data = {
        "name": "J",
        "steps": [
            {
                "name": "S",
                "pgm": "IDCAMS",
                "dds": [
                    {
                        "ddname": "SYSIN",
                        "dsn": "",
                        "disp_words": [],
                        "in_stream": ["   DELETE A.B CLUSTER"],
                        "sysout": False,
                    },
                    {
                        "ddname": "SYSPRINT",
                        "dsn": "",
                        "disp_words": [],
                        "in_stream": [],
                        "sysout": True,
                    },
                ],
            }
        ],
    }
    dds = _job_from_json(data).steps[0].dds
    assert dds[0].in_stream == ("   DELETE A.B CLUSTER",)
    assert dds[1].sysout is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserialize_step_and_job_cond():
    data = {
        "name": "J",
        "cond": [{"code": 0, "op": "NE", "step": ""}],
        "steps": [
            {
                "name": "S",
                "pgm": "P",
                "cond": [{"code": 4, "op": "LT", "step": "A"}],
                "dds": [],
            }
        ],
    }
    job = _job_from_json(data)
    assert job.cond[0].op is CondOp.NE and job.cond[0].code == 0
    assert job.steps[0].conds[0].op is CondOp.LT
    assert job.steps[0].conds[0].step == "A"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserialize_absent_cond_is_empty():
    data = {"name": "J", "steps": [{"name": "S", "pgm": "P", "dds": []}]}
    job = _job_from_json(data)
    assert job.cond == () and job.steps[0].conds == ()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserialize_even_op_fails_loud():
    data = {
        "name": "J",
        "steps": [
            {"name": "S", "pgm": "P", "cond": [{"code": 0, "op": "EVEN"}], "dds": []}
        ],
    }
    with pytest.raises(ValueError):
        _job_from_json(data)
