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
from cobble.dataflow.fixpoint.provenance import MissingProvenance, provenance


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
            origin="LITERAL",
            source=NO_RANGE,
            site="PROGA/MAIN/0",
            definers=(),
            sink="",
            literal="'X'",
        ),
        DepRow(
            program="PROGA",
            via="",
            target=ws_b,
            origin="",
            source=ws_a,
            site="PROGA/MAIN/1",
            definers=("PROGA/MAIN/0",),
            sink="",
            landing=(0,),
        ),
        DepRow(
            program="PROGA",
            via="",
            target=NO_RANGE,
            origin="",
            source=ws_b,
            site="PROGA/MAIN/2",
            definers=("PROGA/MAIN/1",),
            sink="MAP:MAP1",
        ),
    )

    (out_dir / "members" / "MEMBERA" / SINKS_FILE).unlink()
    with pytest.raises(MissingProvenance, match="MEMBERA"):
        tuple(provenance(out_dir))
