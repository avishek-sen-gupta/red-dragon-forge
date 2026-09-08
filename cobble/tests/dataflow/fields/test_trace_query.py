"""Provenance walks over hand-built JSONL traces."""

from __future__ import annotations

import json
from pathlib import Path

from cobble.dataflow.fields.trace_query import (
    BACKWARD,
    FORWARD,
    DepRow,
    load,
    query,
    _resolve,
)
from cobble.dataflow.fields.extent_text import ByteRange


def _jsonl(rows: list[dict], tmp_path: Path) -> Path:
    path = tmp_path / "trace.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n",
        encoding="utf-8",
    )
    return path


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


def test_load_skips_non_dep_rows(tmp_path: Path):
    rows = [
        _dep("P", "A", 0, 8, "B", 10, 18),
        {"kind": "coverage", "taken": 1, "total": 2, "paths": 1, "programs": 1},
        {"kind": "limits", "items": ["x"]},
    ]
    trace = _jsonl(rows, tmp_path)
    deps = load(trace)
    assert len(deps) == 1
