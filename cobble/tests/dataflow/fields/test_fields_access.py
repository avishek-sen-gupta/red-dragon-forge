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
from cobble.dataflow.srccfg.bundle import Bundle, CfgDocumentError, bundle_jsonl
from cobble.dataflow.srccfg.cfg import Atom, Cfg, Node, NodeKind
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


def _assign(*reads: str) -> Node:
    return Node(id="MAIN/0", kind=NodeKind.ASSIGN, paragraph="MAIN", reads=reads)


def _condition(left: str, right: str, node_id: str = "MAIN/0") -> Node:
    return Node(
        id=node_id,
        kind=NodeKind.TEST,
        paragraph="MAIN",
        atom=Atom(text=f"{left} = {right}", left=left, op="==", right=right),
    )


def test_assign_node_uses_reads():
    assert _names_from_node(_assign("WS-A", "WS-B")) == ("WS-A", "WS-B")


def test_test_node_uses_atom_left_right():
    assert _names_from_node(_condition("WS-STATUS", "'Y'")) == ("WS-STATUS",)


def test_test_node_both_sides_real():
    assert set(_names_from_node(_condition("WS-A", "WS-B"))) == {"WS-A", "WS-B"}


def test_names_are_deduped():
    assert _names_from_node(_assign("WS-A", "WS-A")) == ("WS-A",)


def test_synthetics_filtered_from_reads():
    assert _names_from_node(_assign("%HANDLER", "WS-REAL", "FILE:X")) == ("WS-REAL",)


# ---------------------------------------------------------------------------
# accesses — integration via tmp ASG + CFG
# ---------------------------------------------------------------------------


def _write_cfgs(path: Path, *cfgs: Cfg) -> Path:
    path.write_text(
        bundle_jsonl(Bundle(seed=cfgs[0].program, cfgs=cfgs)), encoding="utf-8"
    )
    return path


def _program(name: str, *nodes: Node) -> Cfg:
    return Cfg(program=name, nodes=nodes, edges=())


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
    asg_dir = tmp_path / "asg"
    asg_dir.mkdir()
    (asg_dir / "PROG.json").write_text(
        json.dumps({"programs": [asg]}), encoding="utf-8"
    )
    cfg_path = _write_cfgs(tmp_path / "cfg.jsonl", _program("PROG", _assign("WS-A")))

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
    asg_dir = tmp_path / "asg"
    asg_dir.mkdir()
    (asg_dir / "PROG.json").write_text(
        json.dumps({"programs": [asg]}), encoding="utf-8"
    )
    cfg_path = _write_cfgs(
        tmp_path / "cfg.jsonl",
        _program("PROG", _condition("WS-STATUS", "'Y'", "MAIN/1#test")),
    )

    rows = accesses(cfg_path, asg_dir)

    assert any(r.extent.field_name == "WS-STATUS" for r in rows)


def test_accesses_dedupes_same_site_field(tmp_path: Path) -> None:
    """Same field read twice in the same node produces one row."""
    asg = _minimal_asg(
        "PROG",
        [_field(1, "REC", children=[_field(5, "WS-A", "X(4)", offset=0)])],
    )
    asg_dir = tmp_path / "asg"
    asg_dir.mkdir()
    (asg_dir / "PROG.json").write_text(
        json.dumps({"programs": [asg]}), encoding="utf-8"
    )
    cfg_path = _write_cfgs(
        tmp_path / "cfg.jsonl", _program("PROG", _assign("WS-A", "WS-A"))
    )

    rows = accesses(cfg_path, asg_dir)
    assert len(rows) == 1


def _one_assign_program(tmp_path: Path) -> tuple[Path, Cfg]:
    """An ASG on disk for PROG, and the single CFG that reads WS-A."""
    asg = _minimal_asg(
        "PROG",
        [_field(1, "REC", children=[_field(5, "WS-A", "X(4)", offset=0)])],
    )
    asg_dir = tmp_path / "asg"
    asg_dir.mkdir()
    (asg_dir / "PROG.json").write_text(
        json.dumps({"programs": [asg]}), encoding="utf-8"
    )
    return asg_dir, _program("PROG", _assign("WS-A"))


def test_accesses_reads_the_one_document_shape(tmp_path: Path) -> None:
    """A member file and a closure are the same shape, so accesses reads them alike."""
    asg_dir, cfg = _one_assign_program(tmp_path)
    cfg_path = _write_cfgs(tmp_path / "cfg.jsonl", cfg)

    rows = accesses(cfg_path, asg_dir)

    assert [(row.program, row.extent.field_name) for row in rows] == [("PROG", "WS-A")]


@pytest.mark.parametrize(
    "document",
    (
        [{"program": "PROG", "nodes": [], "edges": []}],
        {"program": "PROG", "nodes": [], "edges": []},
        {"cfgs": [], "calls": []},
    ),
    ids=("bare_list", "bare_object", "one_document"),
)
def test_accesses_refuses_a_pre_bundle_file(tmp_path: Path, document) -> None:
    """The old shapes are rejected by name rather than half-read.

    Reading a bare object here iterated its keys and crashed on `entry["program"]`;
    a bare list read, but could not carry the calls a closure has. Neither is
    tolerated now, so a stale file says so instead of answering with less.
    """
    asg_dir, _ = _one_assign_program(tmp_path)
    cfg_path = tmp_path / "cfg.jsonl"
    cfg_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(CfgDocumentError, match="cobble-srccfg-build"):
        accesses(cfg_path, asg_dir)


def test_accesses_spans_every_program_a_bundle_carries(tmp_path: Path) -> None:
    """A closure holds more than one program; rows come back for each, not just the seed."""
    asg_dir, cfg = _one_assign_program(tmp_path)
    (asg_dir / "PROG2.json").write_text(
        (asg_dir / "PROG.json").read_text(encoding="utf-8").replace("PROG", "PROG2"),
        encoding="utf-8",
    )
    cfg_path = _write_cfgs(
        tmp_path / "cfg.jsonl", cfg, _program("PROG2", _assign("WS-A"))
    )

    rows = accesses(cfg_path, asg_dir)

    assert sorted({row.program for row in rows}) == ["PROG", "PROG2"]


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
