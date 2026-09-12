"""Tests for cobble.dataflow.fields.access and cobble.dataflow.fields.access_query."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cobble.dataflow.fields.access import (
    AccessRow,
    _is_synthetic,
    _names_from_node,
    accesses,
)
from cobble.dataflow.fields.access_query import _overlaps, query
from cobble.dataflow.fields.trace_query import ByteRange

# ---------------------------------------------------------------------------
# _is_synthetic
# ---------------------------------------------------------------------------


def test_percent_prefix_is_synthetic():
    assert _is_synthetic("%HANDLER[ANY]")


def test_colon_is_synthetic():
    assert _is_synthetic("FILE:CUSTFILE")


def test_literal_is_synthetic():
    assert _is_synthetic("'Y'")


def test_digit_start_is_synthetic():
    assert _is_synthetic("0")


def test_empty_is_synthetic():
    assert _is_synthetic("")


def test_plain_name_is_not_synthetic():
    assert not _is_synthetic("WS-STATUS")


# ---------------------------------------------------------------------------
# _names_from_node
# ---------------------------------------------------------------------------


def test_assign_node_uses_reads():
    node = {"kind": "ASSIGN", "reads": ["WS-A", "WS-B"], "atom": {}}
    assert _names_from_node(node) == ("WS-A", "WS-B")


def test_test_node_uses_atom_left_right():
    node = {
        "kind": "TEST",
        "reads": [],
        "atom": {"left": "WS-STATUS", "op": "==", "right": "'Y'"},
    }
    assert _names_from_node(node) == ("WS-STATUS",)  # 'Y' filtered as literal


def test_test_node_both_sides_real():
    node = {
        "kind": "TEST",
        "reads": [],
        "atom": {"left": "WS-A", "op": "==", "right": "WS-B"},
    }
    assert set(_names_from_node(node)) == {"WS-A", "WS-B"}


def test_names_are_deduped():
    node = {"kind": "ASSIGN", "reads": ["WS-A", "WS-A"], "atom": {}}
    assert _names_from_node(node) == ("WS-A",)


def test_synthetics_filtered_from_reads():
    node = {"kind": "ASSIGN", "reads": ["%HANDLER", "WS-REAL", "FILE:X"], "atom": {}}
    assert _names_from_node(node) == ("WS-REAL",)


# ---------------------------------------------------------------------------
# accesses — integration via tmp ASG + CFG
# ---------------------------------------------------------------------------


def _minimal_cfg(program: str, nodes: list[dict]) -> list[dict]:
    return [{"program": program, "nodes": nodes, "edges": []}]


def _minimal_asg(program: str, fields: list[dict]) -> dict:
    return {
        "program_id": program,
        "paragraphs": [{"name": "MAIN", "statements": []}],
        "data_fields": fields,
    }


def _field(level: int, name: str, pic: str = "X(4)", **extra) -> dict:
    entry: dict = {"level": level, "name": name}
    if pic:
        entry["pic"] = pic
    return {**entry, **extra}


def test_accesses_emits_row_for_assign_read(tmp_path: Path) -> None:
    """An ASSIGN node that reads WS-A produces an AccessRow for WS-A."""
    asg = _minimal_asg(
        "PROG",
        [_field(1, "REC", children=[_field(5, "WS-A", "X(4)", offset=0)])],
    )
    cfg = _minimal_cfg(
        "PROG",
        [
            {
                "id": "MAIN/0",
                "kind": "ASSIGN",
                "paragraph": "MAIN",
                "reads": ["WS-A"],
                "writes": [],
                "atom": {},
                "transfer": "",
                "target": "",
                "target_resolved": True,
                "transfer_operand": "",
                "using": [],
            }
        ],
    )
    asg_dir = tmp_path / "asg"
    asg_dir.mkdir()
    (asg_dir / "PROG.json").write_text(json.dumps(asg), encoding="utf-8")
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    rows = accesses(cfg_path, asg_dir)

    assert len(rows) == 1
    assert rows[0].program == "PROG"
    assert rows[0].extent.field_name == "WS-A"
    assert rows[0].paragraph == "MAIN"


def test_accesses_emits_row_for_test_condition(tmp_path: Path) -> None:
    """A TEST node with atom.left = WS-STATUS produces an AccessRow."""
    asg = _minimal_asg(
        "PROG",
        [_field(1, "REC", children=[_field(5, "WS-STATUS", "X(1)", offset=0)])],
    )
    cfg = _minimal_cfg(
        "PROG",
        [
            {
                "id": "MAIN/1#test",
                "kind": "TEST",
                "paragraph": "MAIN",
                "reads": [],
                "writes": [],
                "atom": {"left": "WS-STATUS", "op": "==", "right": "'Y'"},
                "transfer": "",
                "target": "",
                "target_resolved": True,
                "transfer_operand": "",
                "using": [],
            }
        ],
    )
    asg_dir = tmp_path / "asg"
    asg_dir.mkdir()
    (asg_dir / "PROG.json").write_text(json.dumps(asg), encoding="utf-8")
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    rows = accesses(cfg_path, asg_dir)

    assert any(r.extent.field_name == "WS-STATUS" for r in rows)


def test_accesses_dedupes_same_site_field(tmp_path: Path) -> None:
    """Same field read twice in the same node produces one row."""
    asg = _minimal_asg(
        "PROG",
        [_field(1, "REC", children=[_field(5, "WS-A", "X(4)", offset=0)])],
    )
    cfg = _minimal_cfg(
        "PROG",
        [
            {
                "id": "MAIN/0",
                "kind": "ASSIGN",
                "paragraph": "MAIN",
                "reads": ["WS-A", "WS-A"],
                "writes": [],
                "atom": {},
                "transfer": "",
                "target": "",
                "target_resolved": True,
                "transfer_operand": "",
                "using": [],
            }
        ],
    )
    asg_dir = tmp_path / "asg"
    asg_dir.mkdir()
    (asg_dir / "PROG.json").write_text(json.dumps(asg), encoding="utf-8")
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    rows = accesses(cfg_path, asg_dir)
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# _overlaps
# ---------------------------------------------------------------------------


def _root(program: str, region: str, start: int, end: int) -> ByteRange:
    from cobble.dataflow.fields.extent_text import byte_range

    return ByteRange(
        program=program,
        region=region,
        start=start,
        end=end,
        name="F",
        exact=True,
        known=True,
    )


def test_overlaps_matching_extent():
    row = {
        "program": "PROG",
        "extent": {"region": "working_storage", "start": 4, "end": 8},
    }
    root = _root("PROG", "working_storage", 4, 8)
    assert _overlaps(row, root)


def test_overlaps_partial_overlap():
    row = {
        "program": "PROG",
        "extent": {"region": "working_storage", "start": 0, "end": 6},
    }
    root = _root("PROG", "working_storage", 4, 8)
    assert _overlaps(row, root)


def test_no_overlap_different_region():
    row = {"program": "PROG", "extent": {"region": "linkage", "start": 4, "end": 8}}
    root = _root("PROG", "working_storage", 4, 8)
    assert not _overlaps(row, root)


def test_no_overlap_adjacent():
    row = {
        "program": "PROG",
        "extent": {"region": "working_storage", "start": 0, "end": 4},
    }
    root = _root("PROG", "working_storage", 4, 8)
    assert not _overlaps(row, root)


def test_empty_program_in_root_matches_any_program():
    row = {
        "program": "PROG",
        "extent": {"region": "working_storage", "start": 4, "end": 8},
    }
    root = _root("", "working_storage", 4, 8)
    assert _overlaps(row, root)
