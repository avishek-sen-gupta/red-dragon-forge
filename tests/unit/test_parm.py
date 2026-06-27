"""Unit tests for PARM region builder and model/deserializer parm field."""

from __future__ import annotations

import struct

import pytest

from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_build_parm_region_empty():
    from jackal.parm import build_parm_region

    result = build_parm_region("")
    assert result == b"\x00\x00"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_build_parm_region_text():
    from interpreter.cobol.ebcdic_table import EbcdicTable

    from jackal.parm import build_parm_region

    result = build_parm_region("2022071800")
    assert result == b"\x00\x0a" + EbcdicTable.ascii_to_ebcdic(b"2022071800")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_build_parm_region_single_char():
    from interpreter.cobol.ebcdic_table import EbcdicTable

    from jackal.parm import build_parm_region

    result = build_parm_region("X")
    assert result == b"\x00\x01" + EbcdicTable.ascii_to_ebcdic(b"X")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_build_parm_region_too_long_raises():
    from jackal.parm import build_parm_region

    with pytest.raises(ValueError, match="too long"):
        build_parm_region("A" * (0x7FFF + 1))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_step_parm_field_default():
    from jackal.model import Step

    step = Step(name="S", pgm="P", dds=())
    assert step.parm == ""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_step_parm_field_set():
    from jackal.model import Step

    step = Step(name="S", pgm="P", dds=(), parm="2022071800")
    assert step.parm == "2022071800"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserializer_parm_present():
    from jackal.jcl.bridge_parser import _job_from_json

    data = {
        "name": "J",
        "steps": [{"name": "S", "pgm": "P", "parm": "HELLO", "dds": []}],
    }
    job = _job_from_json(data)
    assert job.steps[0].parm == "HELLO"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserializer_parm_absent_defaults_empty():
    from jackal.jcl.bridge_parser import _job_from_json

    data = {"name": "J", "steps": [{"name": "S", "pgm": "P", "dds": []}]}
    job = _job_from_json(data)
    assert job.steps[0].parm == ""
