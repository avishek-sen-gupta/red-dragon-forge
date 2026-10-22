"""JSONL serialisation of the trace report."""

from __future__ import annotations

import json

from cobble.dataflow.fields.state import NOWHERE
from cobble.dataflow.fields.trace import Coverage, DeadEnd, Dep, Trace
from cobble.dataflow.fields.trace_report import (
    _dead_end_row,
    _dep_row,
    _footer_lines,
)
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

WS = RegionId.WORKING_STORAGE

_EXTENT_A = FieldExtent(
    field_name="FIELD-A",
    region=WS,
    start=100,
    length=8,
    precision=Precision.EXACT,
)

_EXTENT_B = FieldExtent(
    field_name="FIELD-B",
    region=WS,
    start=200,
    length=8,
    precision=Precision.EXACT,
)

_EXTENT_C = FieldExtent(
    field_name="FIELD-C",
    region=WS,
    start=300,
    length=4,
    precision=Precision.CLAMPED,
)

_DEP = Dep(
    program="PROG",
    node="PARA/3",
    target=_EXTENT_A,
    origin="",
    source=_EXTENT_B,
    definers=("PROG/PARA/1",),
    via="",
    source_program="PROG",
)

_ORIGIN_DEP = Dep(
    program="PROG",
    node="PARA/5",
    target=_EXTENT_A,
    origin="LITERAL",
    literal="'Y'",
    source=FieldExtent(
        field_name="", region=WS, start=0, length=0, precision=Precision.EXACT
    ),
    definers=(),
    via="",
    source_program="PROG",
)

_DEAD_END = DeadEnd(
    program="PROG",
    node="PARA/14",
    transfer="LINK",
    callee="OTHER",
    reason="callee-not-in-cache",
)


def test_jsonl_round_trips_a_dep():
    parsed = json.loads(_dep_row(_DEP))
    assert parsed["kind"] == "dep"
    assert parsed["program"] == "PROG"
    assert parsed["target"]["field"] == "FIELD-A"
    assert parsed["target"]["start"] == 100
    assert parsed["target"]["end"] == 108
    assert parsed["target"]["clamped"] is False
    assert parsed["source"]["field"] == "FIELD-B"
    assert parsed["source"]["start"] == 200
    assert parsed["origin"] == ""
    assert parsed["site"] == "PROG/PARA/3"
    assert parsed["definers"] == ["PROG/PARA/1"]


def test_jsonl_origin_dep_has_null_source():
    parsed = json.loads(_dep_row(_ORIGIN_DEP))
    assert parsed["origin"] == "LITERAL"
    assert parsed["literal"] == "'Y'"
    assert parsed["source"] is None


def test_a_sink_dep_names_where_its_source_went_and_has_no_target():
    dep = Dep(
        program="PROG",
        node="PARA/9",
        target=NOWHERE,
        origin="",
        source=_EXTENT_B,
        definers=("PROG/PARA/1",),
        via="",
        source_program="PROG",
        sink="FILE:KSDS",
    )
    assert (json.loads(_dep_row(dep)), json.loads(_dep_row(_DEP))["sink"]) == (
        {
            "kind": "dep",
            "program": "PROG",
            "via": "",
            "target": None,
            "origin": "",
            "literal": "",
            "sink": "FILE:KSDS",
            "source": {
                "field": "FIELD-B",
                "region": "working_storage",
                "start": 200,
                "end": 208,
                "clamped": False,
            },
            "source_program": "PROG",
            "site": "PROG/PARA/9",
            "definers": ["PROG/PARA/1"],
        },
        "",
    )


def test_jsonl_clamped_extent():
    dep = Dep(
        program="PROG",
        node="PARA/7",
        target=_EXTENT_C,
        origin="",
        source=_EXTENT_B,
        definers=(),
        via="",
        source_program="PROG",
    )
    parsed = json.loads(_dep_row(dep))
    assert parsed["target"]["clamped"] is True


def test_jsonl_round_trips_a_dead_end():
    parsed = json.loads(_dead_end_row(_DEAD_END))
    assert parsed["kind"] == "dead_end"
    assert parsed["transfer"] == "LINK"
    assert parsed["callee"] == "OTHER"
    assert parsed["reason"] == "callee-not-in-cache"


def test_footer_includes_coverage_and_limits():
    trace = Trace(
        dead_ends=frozenset({_DEAD_END}),
        paths=10,
        coverage=Coverage(
            taken=frozenset({("PROG", "PARA/3", "TRUE")}),
            total=2,
            programs=frozenset({"PROG"}),
        ),
    )
    found = _footer_lines(trace)
    kinds = {json.loads(line)["kind"] for line in found}
    assert kinds == {"dead_end", "coverage", "limits"}
