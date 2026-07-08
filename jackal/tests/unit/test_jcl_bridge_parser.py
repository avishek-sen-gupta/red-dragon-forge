import json
import pytest
from tests.covers import NotLanguageFeature, covers
from jackal.dsn import DirectDSN
from jackal.jcl.bridge_parser import JclBridgeParser, JclParseError
from jackal.value_parts import Literal, Symbol, literal


class _FakeRunner:
    def __init__(self, out=None, exc=None):
        self._out, self._exc = out, exc
        self.command = None

    def run(self, command, input_data):
        self.command = command
        if self._exc:
            raise self._exc
        return self._out


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_builds_model_from_bridge_json():
    out = json.dumps(
        {
            "name": "J",
            "steps": [
                {
                    "name": "S",
                    "pgm": "P",
                    "dds": [
                        {
                            "ddname": "D",
                            "dsn": [{"type": "Literal", "name": "A.B"}],
                            "disp_words": ["SHR"],
                            "in_stream": [],
                            "sysout": False,
                        }
                    ],
                }
            ],
        }
    )
    runner = _FakeRunner(out=out)
    job = JclBridgeParser(runner, "jcl.jar").parse("//J JOB 1\n")
    assert job.steps[0].dds[0].dsn == DirectDSN(literal("A.B"))
    assert runner.command == ["java", "-jar", "jcl.jar"]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_builds_symbol_part_from_bridge_json():
    out = json.dumps(
        {
            "name": "J",
            "steps": [
                {
                    "name": "S",
                    "pgm": "P",
                    "dds": [
                        {
                            "ddname": "D",
                            "dsn": [
                                {"type": "Symbol", "name": "CNTLLIB"},
                                {"type": "Literal", "name": "(REPROCT)"},
                            ],
                            "disp_words": ["SHR"],
                            "in_stream": [],
                            "sysout": False,
                        }
                    ],
                }
            ],
        }
    )
    runner = _FakeRunner(out=out)
    job = JclBridgeParser(runner, "jcl.jar").parse("//J JOB 1\n")
    from jackal.dsn import DirectDSN
    from jackal.value_parts import Literal, Symbol

    assert job.steps[0].dds[0].dsn == DirectDSN(
        (Symbol("CNTLLIB"), Literal("(REPROCT)"))
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_propagates_bridge_failure():
    runner = _FakeRunner(exc=JclParseError("boom"))
    with pytest.raises(JclParseError):
        JclBridgeParser(runner, "jcl.jar").parse("garbage")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_raises_on_malformed_json():
    runner = _FakeRunner(out="not json{")
    with pytest.raises(JclParseError):
        JclBridgeParser(runner, "jcl.jar").parse("//J JOB\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_raises_on_missing_required_key():
    # step is missing "name" — KeyError in _step_from_json
    out = json.dumps({"name": "J", "steps": [{"pgm": "P", "dds": []}]})
    runner = _FakeRunner(out=out)
    with pytest.raises(JclParseError):
        JclBridgeParser(runner, "jcl.jar").parse("//J JOB\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_proc_builds_procdef_from_bridge_json():
    out = json.dumps(
        {
            "name": "REPROC",
            "defaults": {},
            "steps": [
                {
                    "name": "PRC001",
                    "pgm": "IDCAMS",
                    "cond": [],
                    "parm": [],
                    "dds": [
                        {
                            "ddname": "SYSIN",
                            "dsn": [
                                {"type": "Symbol", "name": "CNTLLIB"},
                                {"type": "Literal", "name": "(REPROCT)"},
                            ],
                            "disp_words": ["SHR"],
                            "in_stream": [],
                            "sysout": False,
                        }
                    ],
                    "proc_parms": {},
                }
            ],
        }
    )
    runner = _FakeRunner(out=out)
    proc = JclBridgeParser(runner, "jcl.jar").parse_proc("//REPROC PROC\n")
    assert proc.name == "REPROC"
    assert proc.defaults == {}
    assert proc.steps[0].name == "PRC001"
    assert proc.steps[0].dds[0].dsn == DirectDSN(
        (Symbol("CNTLLIB"), Literal("(REPROCT)"))
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_proc_builds_defaults():
    out = json.dumps(
        {
            "name": "REPROC",
            "defaults": {"CNTLLIB": [{"type": "Literal", "name": "DEFAULT.LIB"}]},
            "steps": [],
        }
    )
    runner = _FakeRunner(out=out)
    proc = JclBridgeParser(runner, "jcl.jar").parse_proc(
        "//REPROC PROC CNTLLIB=DEFAULT.LIB\n"
    )
    assert proc.defaults == {"CNTLLIB": literal("DEFAULT.LIB")}


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_step_from_json_builds_proc_parms():
    out = json.dumps(
        {
            "name": "J",
            "steps": [
                {
                    "name": "S",
                    "pgm": "REPROC",
                    "dds": [],
                    "proc_parms": {
                        "CNTLLIB": [{"type": "Literal", "name": "AWS.M2.CARDDEMO.CNTL"}]
                    },
                }
            ],
        }
    )
    runner = _FakeRunner(out=out)
    job = JclBridgeParser(runner, "jcl.jar").parse("//J JOB 1\n")
    assert job.steps[0].proc_parms == {"CNTLLIB": literal("AWS.M2.CARDDEMO.CNTL")}
