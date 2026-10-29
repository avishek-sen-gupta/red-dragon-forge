"""A fixpoint out-dir read back as the dep rows the trace used to write."""

from __future__ import annotations

import pytest
from tests.dataflow.fields.test_fields_build_corpus import (  # noqa: F401
    _member_json,
    _program,
    corpus,
)

from cobble.dataflow.fields.dep_row import DepRow
from cobble.dataflow.fields.extent_text import NO_RANGE, byte_range
from cobble.dataflow.fixpoint.build_corpus import SINKS_FILE, cli
from cobble.dataflow.fields.origin import NO_ORIGIN, Origin
from cobble.dataflow.fields.origin_kind import OriginKind
from cobble.dataflow.fields.sink import NO_SINK, Sink
from cobble.dataflow.fields.sink_kind import SinkKind
from cobble.dataflow.fixpoint.provenance import MissingProvenance, provenance
from tests.dataflow.fixpoint.fixpoint_dir import fixpoint_dir, flow_row, sink_row


def _literal_moved_and_sent(program_id: str) -> dict:
    program = _program(program_id)
    (paragraph,) = program["paragraphs"]
    return {
        **program,
        "paragraphs": [
            {
                **paragraph,
                "statements": [
                    {"type": "MOVE", "operands": [{"name": "'X'"}, {"name": "WS-A"}]},
                    *paragraph["statements"],
                    {
                        "type": "EXEC_CICS",
                        "verb": "SEND MAP",
                        "options": {
                            "MAP": {"text": "MAP1", "is_literal": True},
                            "FROM": {"text": "WS-B", "is_literal": False},
                        },
                    },
                ],
            }
        ],
    }


def test_a_fixpoint_out_dir_reads_back_as_flow_and_sink_rows(corpus):
    argv, out_dir = corpus({"MEMBERA": _member_json(_literal_moved_and_sent("PROGA"))})
    assert cli(argv) == 0
    ws_a = byte_range("WS-A@working_storage[0:4]", "PROGA")
    ws_b = byte_range("WS-B@working_storage[4:8]", "PROGA")

    assert tuple(provenance(out_dir)) == (
        DepRow(
            program="PROGA",
            via="",
            target=ws_a,
            origin=Origin(OriginKind.LITERAL, "'X'"),
            source=NO_RANGE,
            site="PROGA/MAIN/0",
            definers=(),
            sink=NO_SINK,
        ),
        DepRow(
            program="PROGA",
            via="",
            target=ws_b,
            origin=NO_ORIGIN,
            source=ws_a,
            site="PROGA/MAIN/1",
            definers=("PROGA/MAIN/0",),
            sink=NO_SINK,
            landing=(0,),
        ),
        DepRow(
            program="PROGA",
            via="",
            target=NO_RANGE,
            origin=NO_ORIGIN,
            source=ws_b,
            site="PROGA/MAIN/2",
            definers=("PROGA/MAIN/1",),
            sink=Sink(SinkKind.MAP, "MAP1"),
        ),
    )

    (out_dir / "members" / "MEMBERA" / SINKS_FILE).unlink()
    with pytest.raises(MissingProvenance, match="MEMBERA"):
        tuple(provenance(out_dir))


@pytest.mark.parametrize("old", ["graph", "sinks"])
def test_old_sink_rows_are_stale(tmp_path, old):
    """A run written before origins and sinks were typed is rebuilt, not misread."""
    flow = flow_row("P", "1", "A@working_storage[0:4]", "B@working_storage[4:8]")
    sink = sink_row("P", "2", "A@working_storage[0:4]", Sink(SinkKind.FILE, "OUT"))
    stale = {
        "graph": (flow[0], flow[1].replace('{"kind": "NONE", "name": ""}', '""')),
        "sinks": (
            sink[0],
            sink[1].replace('{"kind": "FILE", "name": "OUT"}', '"FILE:OUT"'),
        ),
    }[old]
    out_dir = fixpoint_dir(
        tmp_path,
        flows=[stale if old == "graph" else flow],
        sinks=[stale if old == "sinks" else sink],
    )
    with pytest.raises(MissingProvenance, match="^.*/members/P has no provenance"):
        tuple(provenance(out_dir))
