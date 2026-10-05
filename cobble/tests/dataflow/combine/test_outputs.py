from pathlib import Path

from cobble.dataflow.combine.edge import Edge
from cobble.dataflow.combine.linked import Linked
from cobble.dataflow.combine.outputs import write_outputs
from cobble.dataflow.combine.run_report import RunReport
from cobble.dataflow.fields.extent_text import byte_range
from cobble.dataflow.jumps.jump_kind import JumpKind
from tests.dataflow.combine.linked_rows import LinkRow, link_rows


def _start(callee_node: str) -> Edge:
    return Edge(
        "S",
        "ST",
        JumpKind.START,
        "R",
        0,
        byte_range("WS-MSG@working_storage[0:8]", "S"),
        byte_range("WS-IN@working_storage[0:8]", "R"),
        callee_node=callee_node,
    )


def test_a_start_into_two_retrieves_writes_a_row_for_each(tmp_path: Path) -> None:
    write_outputs(
        tmp_path,
        Linked(targets=(), edges=(_start("RT1"), _start("RT2")), report=RunReport()),
    )

    row = LinkRow(
        caller="S",
        node="ST",
        transfer="START",
        callee="R",
        caller_extent="WS-MSG@working_storage[0:8]",
        callee_extent="WS-IN@working_storage[0:8]",
        returns=False,
        reason="",
        discovered=False,
    )
    assert link_rows(tmp_path / "links.jsonl") == [row, row]
