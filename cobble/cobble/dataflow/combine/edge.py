"""Edge — one program-to-program link linking used, with its lined-up bytes."""

from dataclasses import dataclass

from cobble.dataflow.fields.extent_text import ByteRange
from cobble.dataflow.jumps.jump_kind import JumpKind


@dataclass(frozen=True)
class Edge:
    caller: str
    node: str
    kind: JumpKind
    callee: str
    param: int
    caller_window: ByteRange
    callee_window: ByteRange
    callee_node: str = ""
    discovered: bool = False
