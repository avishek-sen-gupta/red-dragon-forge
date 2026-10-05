"""Write the linked targets and links tables."""

import json
from pathlib import Path

from cobble.dataflow.combine.edge import Edge
from cobble.dataflow.combine.linked import Linked
from cobble.dataflow.combine.linked_target import LinkedTarget
from cobble.dataflow.fields.side_tables import jsonl_writer, target_row
from cobble.dataflow.jumps.jump_kind import JumpKind

_RETURNS = frozenset({JumpKind.LINK, JumpKind.CALL})


def _target(found: LinkedTarget) -> tuple[str, str]:
    identity, row = target_row(found.target)
    return identity, json.dumps({**json.loads(row), "outside": list(found.outside)})


def _link(edge: Edge) -> tuple[str, str]:
    row = json.dumps(
        {
            "caller": edge.caller,
            "node": edge.node,
            "transfer": edge.kind.value,
            "callee": edge.callee,
            "caller_extent": str(edge.caller_window),
            "callee_extent": str(edge.callee_window),
            "returns": edge.kind in _RETURNS,
            "reason": "",
            "discovered": edge.discovered,
        }
    )
    return f"{edge.caller}\0{edge.node}\0{edge.callee}\0{edge.param}", row


def write_outputs(out_dir: Path, linked: Linked) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with jsonl_writer(out_dir / "targets.jsonl") as targets:
        targets.add_rows(map(_target, linked.targets))
    with jsonl_writer(out_dir / "links.jsonl") as links:
        links.add_rows(map(_link, linked.edges))
