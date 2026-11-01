"""Every read a node makes, tagged with whether its bytes are copied or only consulted."""

from __future__ import annotations

from cobble.dataflow.depgraph.flows import program_context
from cobble.dataflow.srccfg.conditions import condition_index
from cobble.dataflow.srccfg.desugar import Ctx, lower_statements
from cobble.dataflow.srccfg.read import Read, ReadKind

COPIED = ReadKind.COPIED
CONSULTED = ReadKind.CONSULTED


def test_moved_bytes_are_copied_and_subscripts_keys_ridflds_and_tests_are_consulted(
    program_of,
) -> None:
    asg = program_of(
        [
            {
                "type": "MOVE",
                "operands": [
                    {
                        "name": "WS-TBL",
                        "subscripts": [{"kind": "ref", "name": "WS-IND"}],
                    },
                    {"name": "WS-OUT"},
                ],
            },
            {
                "type": "READ",
                "file_name": "CARD-INPUT",
                "into": {"name": "WS-COPY"},
                "key": {"name": "WS-KEY"},
            },
            {
                "type": "EXEC_CICS",
                "verb": "READ",
                "options": {
                    "FILE": {"text": "'ACCTS'", "is_literal": True},
                    "INTO": {"text": "WS-REC"},
                    "RIDFLD": {"text": "WS-RID"},
                    "NOHANDLE": None,
                },
            },
            {
                "type": "IF",
                "condition": {
                    "not": False,
                    "relation": {
                        "left": {"kind": "ref", "name": "WS-FLAG"},
                        "op": "==",
                        "right": {"kind": "lit", "value": "'Y'"},
                    },
                },
                "then": [],
                "else": [],
            },
        ]
    )
    ctx = Ctx(
        program=asg.program_id,
        paragraph="MAIN",
        flows=program_context(asg),
        index=condition_index(asg),
    )
    nodes = lower_statements(asg.paragraphs[0].statements, ctx, "").nodes

    assert {node.id: node.reads for node in nodes if node.reads} == {
        "MAIN/0": (Read("WS-TBL", COPIED), Read("WS-IND", CONSULTED)),
        "MAIN/1": (Read("FILE:CARD-INPUT", COPIED), Read("WS-KEY", CONSULTED)),
        "MAIN/2": (Read("FILE:ACCTS", COPIED), Read("WS-RID", CONSULTED)),
        "MAIN/3#test": (Read("WS-FLAG", CONSULTED),),
    }
