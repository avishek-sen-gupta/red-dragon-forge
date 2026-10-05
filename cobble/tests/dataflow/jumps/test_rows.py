"""A jumps.jsonl row is a lossless spelling of one Jump."""

import json

from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.jump_area import JumpArea
from cobble.dataflow.jumps.rows import jump_from_row, jump_identity, jump_row

JUMP = Jump(
    program="PROGA",
    node="MAIN/3",
    line=12,
    kind=JumpKind.XCTL,
    returns=False,
    target=Fact(
        extent="WS-NEXT@working_storage[20:28]",
        values=("PROGB   ",),
        writers=("MAIN/1",),
    ),
    areas=(
        JumpArea(
            param=0,
            extent="WS-AREA@working_storage[0:20]",
            fields=(
                Fact(
                    extent="WS-FROM@working_storage[0:8]",
                    values=("PROGA   ",),
                    writers=("MAIN/2",),
                ),
                Fact(
                    extent="WS-REST@working_storage[8:20]",
                    reasons=(UnresolvedReason.UNINITIALISED,),
                ),
            ),
        ),
    ),
)


def test_a_jump_round_trips_through_its_row() -> None:
    row = jump_row(JUMP)

    assert json.loads(row) == {
        "program": "PROGA",
        "node": "MAIN/3",
        "line": 12,
        "kind": "XCTL",
        "returns": False,
        "target": {
            "extent": "WS-NEXT@working_storage[20:28]",
            "values": ["PROGB   "],
            "writers": ["MAIN/1"],
            "reasons": [],
        },
        "transid": {"extent": "", "values": [], "writers": [], "reasons": []},
        "areas": [
            {
                "param": 0,
                "extent": "WS-AREA@working_storage[0:20]",
                "fields": [
                    {
                        "extent": "WS-FROM@working_storage[0:8]",
                        "values": ["PROGA   "],
                        "writers": ["MAIN/2"],
                        "reasons": [],
                    },
                    {
                        "extent": "WS-REST@working_storage[8:20]",
                        "values": [],
                        "writers": [],
                        "reasons": ["uninitialised"],
                    },
                ],
            }
        ],
    }
    assert jump_from_row(row) == JUMP
    assert jump_identity(JUMP) == "PROGA\x00MAIN/3\x00XCTL"
