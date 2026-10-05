"""AsgCalleeAreas — callee received areas read from the parse cache, as aliases does."""

from pathlib import Path

from cobble.dataflow.combine.callee_areas import CalleeAreas
from cobble.dataflow.fields.aliases import NO_EXTENT, callee_received_area
from cobble.dataflow.fields.extent_text import (
    NO_RANGE,
    ByteRange,
    byte_range,
    extent_text,
)
from cobble.dataflow.jumps.jump_kind import JumpKind


class AsgCalleeAreas(CalleeAreas):
    def __init__(self, asg_dir: Path) -> None:
        self._asg_dir = asg_dir

    def area(self, callee: str, kind: JumpKind, param: int) -> ByteRange:
        extent = callee_received_area(
            self._asg_dir, callee, kind is JumpKind.CALL, param
        )
        if extent == NO_EXTENT:
            return NO_RANGE
        return byte_range(extent_text(extent), callee)
