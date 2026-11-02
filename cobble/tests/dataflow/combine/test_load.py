"""One program's fixpoint tables, indexed by node and byte range for linking."""

import json
from pathlib import Path

import pytest
from cobble.dataflow.combine.flow import Flow
from cobble.dataflow.combine.load import load_tables
from cobble.dataflow.combine.target_site import TargetSite
from cobble.dataflow.fields.extent_text import byte_range
from cobble.dataflow.fields.origin import Origin
from cobble.dataflow.fields.origin_kind import OriginKind
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.fixpoint.provenance import MissingProvenance
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_area import JumpArea
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.rows import jump_row

P = "PROGB"


def _write(directory: Path, name: str, rows: list[str]) -> None:
    (directory / name).write_text("".join(row + "\n" for row in rows))


def test_tables_index_facts_flows_jumps_received_and_sites(tmp_path: Path) -> None:
    """A jump's facts are its target, its transaction id and each field it hands over."""
    member = tmp_path / "members" / P
    member.mkdir(parents=True)
    _write(
        member,
        "defs.jsonl",
        [
            json.dumps(
                {
                    "program": P,
                    "node": "MAIN/2",
                    "extent": "LK-FROM@linkage[0:8]",
                    "definers": [],
                    "values": [],
                    "reasons": ["inbound-linkage"],
                    "kind": "copied",
                }
            )
        ],
    )
    _write(
        member,
        "graph.jsonl",
        [
            json.dumps({"type": "node", "id": "PROGB.WS-NEXT", "kind": "FIELD"}),
            json.dumps(
                {
                    "type": "edge",
                    "source": "PROGB.LK-FROM",
                    "source_kind": "FIELD",
                    "target": "PROGB.WS-NEXT",
                    "target_kind": "FIELD",
                    "kind": "FLOWS_TO",
                    "attrs": {
                        "node": "MAIN/2",
                        "source_extent": "LK-FROM@linkage[0:8]",
                        "target_extent": "WS-NEXT@working_storage[0:8]",
                        "origin": {"kind": "NONE", "name": ""},
                        "landing": [0],
                        "rebuilt": False,
                    },
                }
            ),
            json.dumps(
                {
                    "type": "edge",
                    "source": "PROGB.LK-FROM",
                    "source_kind": "FIELD",
                    "target": "PROGB.WS-NEXT",
                    "target_kind": "FIELD",
                    "kind": "READS",
                    "attrs": {
                        "node": "MAIN/9",
                        "source_extent": "LK-FROM@linkage[0:8]",
                        "target_extent": "WS-NEXT@working_storage[0:8]",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "edge",
                    "source": "PROGB.LITERAL",
                    "source_kind": "FIELD",
                    "target": "PROGB.WS-NEXT",
                    "target_kind": "FIELD",
                    "kind": "FLOWS_TO",
                    "attrs": {
                        "node": "MAIN/1",
                        "source_extent": "",
                        "target_extent": "WS-NEXT@working_storage[0:8]",
                        "origin": {"kind": "LITERAL", "name": "'PROGM'"},
                        "landing": [],
                        "rebuilt": False,
                    },
                }
            ),
        ],
    )
    jump = Jump(
        P,
        "MAIN/3",
        9,
        JumpKind.XCTL,
        False,
        target=Fact(
            "WS-NEXT@working_storage[0:8]", ("PROGM   ",), ("MAIN/1", "MAIN/2")
        ),
    )
    entry = Jump(
        P,
        "",
        0,
        JumpKind.ENTRY,
        False,
        areas=(JumpArea(0, "DFHCOMMAREA@linkage[0:20]"),),
    )
    tid = Fact("WS-TRAN@working_storage[20:24]", ("CAUP",))
    area = Fact("WS-AREA@working_storage[24:40]", writers=("MAIN/2",))
    returned = Jump(
        P,
        "MAIN/4",
        12,
        JumpKind.RETURN_TRANSID,
        False,
        transid=tid,
        areas=(JumpArea(0, "WS-AREA@working_storage[24:40]", (area,)),),
    )
    _write(
        member,
        "jumps.jsonl",
        [jump_row(entry), jump_row(jump), jump_row(returned)],
    )
    _write(
        member,
        "targets.jsonl",
        [
            json.dumps(
                {
                    "caller": P,
                    "node": "MAIN/3",
                    "transfer": "CICS_XCTL",
                    "expression": "WS-NEXT",
                    "candidates": ["PROGM"],
                    "reasons": ["inbound-linkage"],
                    "dropped": [],
                }
            )
        ],
    )

    tables = load_tables(tmp_path, P)

    lk = byte_range("LK-FROM@linkage[0:8]", P)
    ws = byte_range("WS-NEXT@working_storage[0:8]", P)
    assert tables.facts == {
        "MAIN/2": (
            (
                lk,
                Fact(
                    "LK-FROM@linkage[0:8]", reasons=(UnresolvedReason.INBOUND_LINKAGE,)
                ),
            ),
        ),
        "MAIN/3": ((ws, jump.target),),
        "MAIN/4": (
            (byte_range("WS-TRAN@working_storage[20:24]", P), tid),
            (byte_range("WS-AREA@working_storage[24:40]", P), area),
        ),
    }
    assert tables.flows == {
        "MAIN/2": (Flow("MAIN/2", lk, ws, landing=(0,)),),
        "MAIN/1": (
            Flow(
                "MAIN/1",
                byte_range("", P),
                ws,
                origin=Origin(OriginKind.LITERAL, "'PROGM'"),
            ),
        ),
    }
    assert tables.jumps == {"MAIN/3": jump, "MAIN/4": returned}
    assert tables.received == ((0, byte_range("DFHCOMMAREA@linkage[0:20]", P)),)
    assert tables.sites == {"MAIN/3": TargetSite("CICS_XCTL", "WS-NEXT")}
    assert tables.received_param(byte_range("X@linkage[4:8]", P)) == (0,)
    assert tables.received_param(byte_range("X@linkage[30:34]", P)) == ()
    assert (
        tables.facts_at("MAIN/2", byte_range("X@linkage[2:4]", P))
        == tables.facts["MAIN/2"]
    )


def test_a_member_written_before_flows_carried_their_landing_is_refused(
    tmp_path: Path,
) -> None:
    member = tmp_path / "members" / P
    member.mkdir(parents=True)
    _write(
        member,
        "graph.jsonl",
        [
            json.dumps(
                {
                    "type": "edge",
                    "kind": "FLOWS_TO",
                    "attrs": {
                        "node": "MAIN/2",
                        "source_extent": "LK-FROM@linkage[0:8]",
                        "target_extent": "WS-NEXT@working_storage[0:8]",
                    },
                }
            )
        ],
    )

    with pytest.raises(
        MissingProvenance,
        match=f"^{member} has no provenance .*rerun cobble-dataflow-fixpoint with --force$",
    ):
        load_tables(tmp_path, P)
