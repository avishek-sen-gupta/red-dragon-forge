"""CalleeAreas — where a callee receives the bytes a jump hands it."""

from typing import Protocol

from cobble.dataflow.fields.extent_text import ByteRange
from cobble.dataflow.jumps.jump_kind import JumpKind


class CalleeAreas(Protocol):
    def area(self, callee: str, kind: JumpKind, param: int) -> ByteRange: ...
