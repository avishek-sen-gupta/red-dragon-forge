"""Unit tests for PARM region builder and model/deserializer parm field."""

from __future__ import annotations

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.value_parts import literal


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_build_parm_region_empty():
    from jackal.parm import build_parm_region

    result = build_parm_region("")
    assert result == b"\x00\x00"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_build_parm_region_text():
    from interpreter.encoding.ebcdic_table import EbcdicTable

    from jackal.parm import build_parm_region

    result = build_parm_region("2022071800")
    assert result == b"\x00\x0a" + EbcdicTable.ascii_to_ebcdic(b"2022071800")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_build_parm_region_single_char():
    from interpreter.encoding.ebcdic_table import EbcdicTable

    from jackal.parm import build_parm_region

    result = build_parm_region("X")
    assert result == b"\x00\x01" + EbcdicTable.ascii_to_ebcdic(b"X")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_build_parm_region_too_long_raises():
    from jackal.parm import build_parm_region

    with pytest.raises(ValueError, match="too long"):
        build_parm_region("A" * (0x7FFF + 1))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserializer_parm_present_and_absent():
    from jackal.jcl.bridge_parser import job_from_bridge_json
    from tests.wire_build import job_json, lit, program

    job = job_from_bridge_json(
        job_json("J", (program("S", "P", parm=(lit("HELLO"),)), program("T", "P")))
    )
    assert [s.parm for s in job.steps] == [literal("HELLO"), ()]
