from tests.covers import NotLanguageFeature, covers
from jackal.jcl.bridge_parser import _job_from_json
from jackal.model import DispNormal, DispStatus


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
