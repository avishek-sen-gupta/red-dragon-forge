import json
import pytest
from tests.covers import NotLanguageFeature, covers
from tests.wire_build import (
    dd,
    job_json,
    lit,
    name_dsn,
    proc_call,
    proc_json,
    program,
    sym,
)
from jackal.dsn import DirectDSN
from jackal.jcl import wire
from jackal.jcl.bridge_parser import JclBridgeParser, JclParseError
from jackal.model import ProcCall, ProcRef, StepName
from jackal.value_parts import Literal, Symbol, SymbolName, literal


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
    out = job_json(
        "J",
        (
            program(
                "S",
                "P",
                (
                    dd("D", name_dsn("A.B"), ("SHR",)),
                    dd(
                        "E",
                        wire.NameDsn(value=(sym("CNTLLIB"), lit("(REPROCT)"))),
                        ("SHR",),
                    ),
                ),
            ),
        ),
    )
    runner = _FakeRunner(out=out)
    job = JclBridgeParser(runner, "jcl.jar").parse("//J JOB 1\n")
    assert [d.dsn for d in job.steps[0].dds] == [
        DirectDSN(literal("A.B")),
        DirectDSN((Symbol(SymbolName("CNTLLIB")), Literal("(REPROCT)"))),
    ]
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
def test_parse_raises_on_output_that_breaks_the_contract():
    out = json.dumps({"kind": "job", "name": "J", "statements": []})
    runner = _FakeRunner(out=out)
    with pytest.raises(JclParseError):
        JclBridgeParser(runner, "jcl.jar").parse("//J JOB\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_proc_builds_procdef_from_bridge_json():
    out = proc_json(
        "REPROC",
        (wire.SymbolValue(name="CNTLLIB", value=(lit("DEFAULT.LIB"),)),),
        (
            program(
                "PRC001",
                "IDCAMS",
                (
                    dd(
                        "SYSIN",
                        wire.NameDsn(value=(sym("CNTLLIB"), lit("(REPROCT)"))),
                        ("SHR",),
                    ),
                ),
            ),
        ),
    )
    runner = _FakeRunner(out=out)
    proc = JclBridgeParser(runner, "jcl.jar").parse_proc("//REPROC PROC\n")
    assert proc.name == "REPROC"
    assert proc.defaults == ((SymbolName("CNTLLIB"), literal("DEFAULT.LIB")),)
    assert proc.steps[0].label == StepName("PRC001")
    assert proc.steps[0].dds[0].dsn == DirectDSN(
        (Symbol(SymbolName("CNTLLIB")), Literal("(REPROCT)"))
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_proc_call_carries_its_symbol_overrides():
    out = job_json(
        "J",
        (
            proc_call(
                "S",
                "REPROC",
                (
                    wire.SymbolValue(
                        name="CNTLLIB", value=(lit("AWS.M2.CARDDEMO.CNTL"),)
                    ),
                ),
            ),
        ),
    )
    runner = _FakeRunner(out=out)
    job = JclBridgeParser(runner, "jcl.jar").parse("//J JOB 1\n")
    assert job.steps[0] == ProcCall(
        StepName("S"),
        ProcRef("REPROC"),
        ((SymbolName("CNTLLIB"), literal("AWS.M2.CARDDEMO.CNTL")),),
    )
