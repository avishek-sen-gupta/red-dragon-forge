"""Stop — one place a value's bytes come from that this program cannot see past."""

from dataclasses import dataclass

from cobble.dataflow.combine.stop_kind import StopKind
from cobble.dataflow.fields.extent_text import NO_RANGE, ByteRange
from cobble.dataflow.fields.values import UnresolvedReason


@dataclass(frozen=True)
class Stop:
    kind: StopKind
    at: ByteRange = NO_RANGE
    node: str = ""
    param: int = 0
    reasons: tuple[UnresolvedReason, ...] = ()
