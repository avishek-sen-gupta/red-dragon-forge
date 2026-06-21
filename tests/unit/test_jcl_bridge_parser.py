import json
import pytest
from tests.covers import NotLanguageFeature, covers
from jackal.jcl.bridge_parser import JclBridgeParser, JclParseError


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
                            "dsn": "A.B",
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
    assert job.steps[0].dds[0].dsn == "A.B"
    assert runner.command == ["java", "-jar", "jcl.jar"]


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
