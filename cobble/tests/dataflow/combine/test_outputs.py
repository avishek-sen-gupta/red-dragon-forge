from pathlib import Path

from cobble.dataflow.combine.edge import Edge
from cobble.dataflow.combine.linked import Linked
from cobble.dataflow.combine.outputs import write_outputs
from cobble.dataflow.combine.run_report import RunReport
from cobble.dataflow.fields.extent_text import byte_range
from cobble.dataflow.jumps.jump_kind import JumpKind
from tests.dataflow.combine.linked_rows import LinkRow, link_rows


def _start(callee_node: str, window: str) -> Edge:
    return Edge(
        "S",
        "ST",
        JumpKind.START,
        "R",
        0,
        byte_range("WS-MSG@working_storage[0:8]", "S"),
        byte_range(window, "R"),
        callee_node=callee_node,
    )


def _row(callee_extent: str) -> LinkRow:
    return LinkRow(
        caller="S",
        node="ST",
        transfer="START",
        callee="R",
        caller_extent="WS-MSG@working_storage[0:8]",
        callee_extent=callee_extent,
        returns=False,
        reason="",
        discovered=False,
    )


def _written(tmp_path: Path, *edges: Edge) -> list[LinkRow]:
    write_outputs(tmp_path, (Linked(targets=(), edges=edges, report=RunReport()),))
    return link_rows(tmp_path / "links.jsonl")


def test_a_link_row_is_identified_by_everything_it_says(tmp_path: Path) -> None:
    differing = _written(
        tmp_path / "differ",
        _start("RT1", "WS-IN@working_storage[0:8]"),
        _start("RT2", "WS-ALT@working_storage[8:16]"),
    )
    same = _written(
        tmp_path / "same",
        _start("RT1", "WS-IN@working_storage[0:8]"),
        _start("RT2", "WS-IN@working_storage[0:8]"),
    )

    assert differing == [
        _row("WS-IN@working_storage[0:8]"),
        _row("WS-ALT@working_storage[8:16]"),
    ]
    assert same == [_row("WS-IN@working_storage[0:8]")]
