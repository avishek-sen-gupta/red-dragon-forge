"""Provenance walks over hand-built fixpoint out-dirs and combine links."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from tests.dataflow.fixpoint.fixpoint_dir import fixpoint_dir, flow_row, sink_row

from cobble.dataflow.combine.link_row import LinkRow
from cobble.dataflow.fields.dep_row import DepRow
from cobble.dataflow.fields.extent_text import ByteRange
from cobble.dataflow.fields.trace_query import (
    BACKWARD,
    FORWARD,
    _narrow_sources,
    _narrowed,
    _resolve,
    cli,
    provenance_rows,
    query,
)


def _text(found: dict) -> str:
    return f"{found['field']}@{found['region']}[{found['start']}:{found['end']}]"


def _out_dir(rows: list[dict], tmp_path: Path) -> Path:
    def node(row: dict) -> str:
        return row["site"].split("/", 1)[1]

    flows = [
        flow_row(
            row["program"],
            node(row),
            _text(row["target"]),
            _text(row["source"]) if row["source"] else "",
            row["origin"],
        )
        for row in rows
        if not row.get("sink")
    ]
    sinks = [
        sink_row(row["program"], node(row), _text(row["source"]), row["sink"])
        for row in rows
        if row.get("sink")
    ]
    return fixpoint_dir(tmp_path / "fixpoint", flows, sinks)


def _jsonl(rows: list[dict], tmp_path: Path) -> tuple[DepRow, ...]:
    return provenance_rows(_out_dir(rows, tmp_path), Path())


def _dep(
    program: str,
    target_field: str,
    target_start: int,
    target_end: int,
    source_field: str = "",
    source_start: int = 0,
    source_end: int = 0,
    origin: str = "",
    site: str = "",
    definers: list[str] | None = None,
    via: str = "",
    region: str = "working_storage",
    source_program: str = "",
) -> dict:
    source = (
        {
            "field": source_field,
            "region": region,
            "start": source_start,
            "end": source_end,
            "clamped": False,
        }
        if not origin
        else None
    )
    return {
        "kind": "dep",
        "program": program,
        "via": via,
        "target": {
            "field": target_field,
            "region": region,
            "start": target_start,
            "end": target_end,
            "clamped": False,
        },
        "origin": origin,
        "source": source,
        **({} if origin else {"source_program": source_program or program}),
        "site": site or f"{program}/PARA/0",
        "definers": definers or [],
    }


def test_forward_one_hop(tmp_path: Path):
    trace = _jsonl(
        [
            _dep("P", "COMM", 0, 100, "DFHCOMMAREA", 0, 100, site="P/ENTRY/0"),
        ],
        tmp_path,
    )
    result = query(trace, FORWARD, "DFHCOMMAREA")
    assert any("COMM@working_storage[0:100]" in line for line in result)


def test_forward_two_hops(tmp_path: Path):
    trace = _jsonl(
        [
            _dep("P", "COMM", 0, 100, "DFHCOMMAREA", 0, 100, site="P/ENTRY/0"),
            _dep("P", "K-FIELD", 500, 501, "COMM", 50, 51, site="P/UPDATE/3"),
        ],
        tmp_path,
    )
    result = query(trace, FORWARD, "DFHCOMMAREA", max_depth=3)
    texts = "\n".join(result)
    assert "COMM@working_storage[0:100]" in texts
    assert "K-FIELD@working_storage[500:501]" in texts


def test_backward_one_hop(tmp_path: Path):
    trace = _jsonl(
        [
            _dep("P", "K-FIELD", 500, 501, "IRA-APPS", 50, 51, site="P/UPDATE/3"),
        ],
        tmp_path,
    )
    result = query(trace, BACKWARD, "K-FIELD")
    assert any("IRA-APPS@working_storage[50:51]" in line for line in result)


def test_backward_reaches_terminal_origin(tmp_path: Path):
    trace = _jsonl(
        [
            _dep(
                "P",
                "MASTER",
                0,
                200,
                origin="FILE:ACCTDAT",
                site="P/READ/3",
            ),
        ],
        tmp_path,
    )
    result = query(trace, BACKWARD, "MASTER")
    texts = "\n".join(result)
    assert "FILE:ACCTDAT" in texts


def test_forward_ends_at_the_sink_a_field_was_written_to(tmp_path: Path):
    sunk = {
        **_dep("P", "", 0, 0, "WS-REC", 0, 8, site="P/MAIN/4"),
        "target": None,
        "sink": "FILE:KSDS",
    }
    trace = _jsonl(
        [_dep("P", "WS-REC", 0, 8, "WS-IN", 100, 108, site="P/MAIN/3"), sunk],
        tmp_path,
    )
    assert query(trace, FORWARD, "WS-IN") == (
        "WS-IN@working_storage[100:108]",
        "  -> WS-REC@working_storage[0:8]  at P/MAIN/3",
        "    -> FILE:KSDS  at P/MAIN/4",
    )


def test_qualified_field_filters_by_program(tmp_path: Path):
    trace = _jsonl(
        [
            _dep("P", "FIELD-X", 10, 11, "SRC-A", 20, 21, site="P/PARA/0"),
            _dep("Q", "FIELD-X", 10, 11, "SRC-B", 30, 31, site="Q/PARA/0"),
        ],
        tmp_path,
    )
    result_p = query(trace, FORWARD, "SRC-A")
    result_q = query(trace, FORWARD, "SRC-B")
    p_text = "\n".join(result_p)
    q_text = "\n".join(result_q)
    assert "FIELD-X" in p_text
    assert "FIELD-X" in q_text


def test_depth_limit_stops_walk(tmp_path: Path):
    trace = _jsonl(
        [
            _dep("P", "B", 100, 108, "A", 0, 8, site="P/S1/0"),
            _dep("P", "C", 200, 208, "B", 100, 108, site="P/S2/0"),
            _dep("P", "D", 300, 308, "C", 200, 208, site="P/S3/0"),
        ],
        tmp_path,
    )
    result_1 = query(trace, FORWARD, "A", max_depth=1)
    result_3 = query(trace, FORWARD, "A", max_depth=3)
    text_1 = "\n".join(result_1)
    text_3 = "\n".join(result_3)
    assert "B@working_storage[100:108]" in text_1
    assert "C@working_storage[200:208]" not in text_1
    assert "D@working_storage[300:308]" in text_3


def test_field_not_found(tmp_path: Path):
    trace = _jsonl(
        [_dep("P", "FIELD-A", 10, 11, "SRC", 20, 21)],
        tmp_path,
    )
    result = query(trace, FORWARD, "NO-SUCH-FIELD")
    assert any("not found" in line for line in result)


def _range(program: str, name: str, start: int, end: int) -> ByteRange:
    return ByteRange(
        program=program,
        region="working_storage",
        start=start,
        end=end,
        name=name,
        exact=True,
        known=True,
    )


def test_backward_crosses_into_a_callee_through_a_returning_link(tmp_path: Path):
    """Each program's rows stay in that program; a combine link window is what
    carries the walk across, both ways when the call returns."""
    out = _out_dir(
        [_dep("CALLEE", "SUB-RESULT", 4, 8, "SUB-CODE", 0, 4, site="CALLEE/CALC/0")],
        tmp_path,
    )
    links = tmp_path / "links.jsonl"
    links.write_text(
        LinkRow(
            caller="CALLER",
            node="LINK/0",
            callee="CALLEE",
            caller_extent="WS-AREA@working_storage[4:8]",
            callee_extent="SUB-RESULT@working_storage[4:8]",
            returns=True,
        ).model_dump_json()
        + "\n",
        encoding="utf-8",
    )

    crossed = "\n".join(query(provenance_rows(out, links), BACKWARD, "CALLER.WS-AREA"))
    alone = "\n".join(query(provenance_rows(out, Path()), BACKWARD, "CALLER.WS-AREA"))

    assert "CALLEE/CALC/0" in crossed
    assert "CALLEE/CALC/0" not in alone


def test_a_program_the_out_dir_does_not_hold_exits_two(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    out = _out_dir([_dep("P", "A", 0, 8, "B", 10, 18)], tmp_path)

    with caplog.at_level(logging.ERROR):
        code = cli(["forward", "NOPE.FIELD", "--fixpoint", str(out)])

    assert code == 2
    assert [record.getMessage() for record in caplog.records] == [
        f"trace-query: no member NOPE under {out}"
    ]


def test_a_frontier_range_wider_than_the_target_narrows_to_their_overlap():
    """Tracing a group and one of its members at once puts both on the frontier.
    Offsetting the source by the wider one's start slides it off the front."""
    source = _range("CALLEE", "SUB-RESULT", 4, 8)
    target = _range("CALLER", "WS-AREA", 4, 8)

    assert _narrowed(source, target, _range("CALLER", "WS-AREA", 0, 8)) == source


def test_every_overlapping_frontier_range_yields_its_own_slice():
    """One slice per overlap, not the first of them: the frontier is built from a
    set, so "the first" is whatever order it happened to come out in."""
    source = _range("CALLEE", "SUB-REC", 0, 8)
    dep = DepRow(
        program="CALLER",
        via="",
        target=_range("CALLER", "WS-AREA", 0, 8),
        origin="",
        source=source,
        site="CALLER/LINK/0",
        definers=(),
        sink="",
    )
    frontier = (_range("CALLER", "WS-KEY", 0, 4), _range("CALLER", "WS-VAL", 4, 8))

    assert _narrow_sources(dep, frontier) == (
        _range("CALLEE", "SUB-REC", 0, 4),
        _range("CALLEE", "SUB-REC", 4, 8),
    )
